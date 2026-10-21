#!/usr/bin/env python3
"""Quick "are the LiDAR and the IMU alive?" check for Sourccey.

Unlike the two camera checks, this one runs **on the Raspberry Pi** — SSH in and
run it there. It has to: the LiDAR is a serial device and the IMU is on the Pi's
I2C bus, and with the default configuration `sourccey-host` publishes neither of them to the
network. The observation stream the teleop client subscribes to carries arm
state, base velocity, and camera frames only, so there is nothing for a PC-side
client to read. (See the runbook for what adding a host-side sensor publisher
would take.)

    # both checks: 5s of LiDAR, 3s of IMU
    uv run --no-sync sourccey-check-lidar-imu

    # LiDAR only, longer listen, different serial port
    uv run --no-sync sourccey-check-lidar-imu --skip-imu \
        --lidar-port /dev/ttyUSB1 --lidar-seconds 10

    # IMU only, plus an interactive yaw test
    uv run --no-sync sourccey-check-lidar-imu --skip-lidar --spin-test

The LiDAR is opened briefly and released as soon as the check ends; nothing is
driven and no arm is commanded. Per the stack's hard directives there are no
silent fallbacks: anything that cannot be verified is reported as FAIL with the
reason, and the exit code is non-zero.
"""

from __future__ import annotations

import argparse
import math
import os
import statistics
import time

from lerobot_robot_sourccey.sensors.imu import (
    AdafruitLSM6DSOXLIS3MDLIMU,
    IMUConfig,
    IMUSample,
)
from lerobot_robot_sourccey.sensors.lidar.ld19 import (
    DEFAULT_BAUDRATE,
    DEFAULT_DEVICE,
    LD19Parser,
)
from lerobot_robot_sourccey.sensors.lidar.types import LidarPoint

# LD06 confidence below this is noise rather than a surface return.
MIN_CONFIDENCE = 100
# A healthy LD06 spins around 5-13 Hz; below this it is stalled or unpowered.
MIN_RPM = 120.0
# Fraction of the 360 one-degree bins a healthy listen window should touch.
MIN_ANGULAR_COVERAGE = 0.7
# Gravity bounds for a stationary robot, generous enough for a hand-held Pi.
ACCEL_MIN_M_S2, ACCEL_MAX_M_S2 = 6.0, 14.0


def check_lidar(args: argparse.Namespace) -> bool:
    """Briefly listen to the LiDAR and report whether it returns real scans."""
    print("[lidar] ---- LiDAR check ----")
    print(f"[lidar] listening for {args.lidar_seconds:.1f}s on {args.lidar_port} @ {args.lidar_baud}")

    if not os.path.exists(args.lidar_port):
        print(f"[lidar] FAIL  no such serial device: {args.lidar_port}")
        print("[lidar]       list what IS there with `ls -l /dev/ttyUSB* /dev/ttyACM*`, then")
        print("[lidar]       re-run with --lidar-port; also check the LiDAR's USB cable/power")
        return False

    try:
        import serial
    except ImportError:
        print('[lidar] FAIL  pyserial is not installed (install "lerobot-robot-sourccey[robot]")')
        return False

    points: list[LidarPoint] = []
    parser = LD19Parser()
    speeds: list[float] = []
    packets = 0
    try:
        ser = serial.Serial(args.lidar_port, args.lidar_baud, timeout=1.0)
    except Exception as exc:  # noqa: BLE001 - surface the driver's own message
        print(f"[lidar] FAIL  could not open {args.lidar_port}: {exc}")
        if "permission" in str(exc).lower():
            print("[lidar]       permission denied - add your user to the `dialout` group, re-login")
        else:
            print("[lidar]       if another process is streaming the LiDAR it owns the port; stop it")
        return False

    try:
        ser.reset_input_buffer()
        deadline = time.monotonic() + args.lidar_seconds
        while time.monotonic() < deadline:
            chunk = ser.read(max(1, min(int(ser.in_waiting), 4096)))
            for packet in parser.feed(chunk):
                packets += 1
                speeds.append(packet.speed_deg_s)
                points.extend(packet.points)
    except TimeoutError as exc:
        print(f"[lidar] serial read stalled: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"[lidar] FAIL  error while reading: {exc}")
        return False
    finally:
        ser.close()

    if not points:
        print(f"[lidar] FAIL  no scan data at all ({packets} packets received)")
        print("[lidar]       the LiDAR is unpowered, unplugged, or on a different port")
        return False

    if parser.crc_error_count:
        print(f"[lidar] WARN  {parser.crc_error_count} packets failed CRC validation")

    rpm = statistics.mean(speeds) / 6.0 if speeds else 0.0
    valid = [p for p in points if p.distance_m > 0.0 and p.intensity >= MIN_CONFIDENCE]
    # Split the REJECTED points, because the two causes mean opposite things:
    # a zero distance is "nothing came back" (open space, or beyond range), while
    # a weak return is "something came back but faintly" - a dirty or fogged
    # window, a very dark/angled surface, or a confidence threshold set too high.
    no_return = [p for p in points if p.distance_m <= 0.0]
    weak = [p for p in points if p.distance_m > 0.0 and p.intensity < MIN_CONFIDENCE]
    distances = sorted(p.distance_m for p in valid)
    coverage = len({int(p.angle_deg) % 360 for p in valid}) / 360.0

    print(f"[lidar] {packets} packets, {len(points)} points, {len(valid)} valid returns")
    print(f"[lidar] spin rate  {rpm:.1f} rpm ({rpm / 60.0:.1f} Hz)")
    print(
        f"[lidar] coverage   {coverage * 100:.0f}% of the 360 deg circle, "
        f"{len(valid) / len(points) * 100:.0f}% of points valid"
    )
    print(
        f"[lidar] rejected   {len(no_return)} with no return (open space or out of range), "
        f"{len(weak)} too weak (confidence < {MIN_CONFIDENCE})"
    )
    if weak:
        weak_confidence = sorted(p.intensity for p in weak)
        print(
            f"[lidar]            weak-return confidence: min={weak_confidence[0]} "
            f"median={weak_confidence[len(weak_confidence) // 2]} max={weak_confidence[-1]}"
        )
    if distances:
        print(
            f"[lidar] distances  min={distances[0]:.2f}m "
            f"median={distances[len(distances) // 2]:.2f}m max={distances[-1]:.2f}m"
        )

    ok = True
    if rpm < MIN_RPM:
        print(f"[lidar] FAIL  spin rate {rpm:.1f} rpm is below {MIN_RPM:.0f} - motor stalled/unpowered")
        ok = False
    if not valid:
        print("[lidar] FAIL  packets arrive but no point clears the confidence threshold")
        ok = False
    elif coverage < MIN_ANGULAR_COVERAGE:
        print(f"[lidar] WARN  only {coverage * 100:.0f}% angular coverage")
        if len(weak) > len(no_return):
            print(
                "[lidar]       most rejected points came back TOO WEAK rather than not at "
                "all, which points at a dirty/fogged window or an obstructed rotor"
            )
        else:
            print(
                "[lidar]       most rejected points had no return at all - expected if the "
                "robot is on a bench in open space, suspicious in a room with walls"
            )
        print("[lidar]       re-run facing a wall about 1m away: coverage should jump")
    if ok:
        print("[lidar] PASS  LiDAR is spinning and returning real scan data")
    return ok


def check_imu(args: argparse.Namespace) -> bool:
    """Read the I2C IMU and report whether it produces sane, changing data."""
    print()
    print("[imu] ---- IMU check ----")
    imu = AdafruitLSM6DSOXLIS3MDLIMU(
        IMUConfig(
            bus_num=args.imu_bus,
            lsm6dsox_address=args.imu_accel_address,
            lis3mdl_address=args.imu_mag_address,
        )
    )
    try:
        imu.connect()
    except ImportError as exc:
        print(f"[imu] FAIL  the Adafruit I2C drivers are not installed: {exc}")
        print(
            "[imu]       uv pip install adafruit-blinka adafruit-circuitpython-lsm6ds "
            "adafruit-circuitpython-lis3mdl"
        )
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"[imu] FAIL  could not connect: {exc}")
        print(
            f"[imu]       check the wiring and `i2cdetect -y {args.imu_bus}` - expect "
            f"0x{args.imu_accel_address:02X} (LSM6DSOX) and 0x{args.imu_mag_address:02X} (LIS3MDL)"
        )
        return False

    print(
        f"[imu] connected on i2c-{args.imu_bus} (LSM6-family + LIS3MDL); sampling for "
        f"{args.imu_seconds:.1f}s (hold the robot still)"
    )
    samples: list[IMUSample] = []
    try:
        deadline = time.monotonic() + args.imu_seconds
        while time.monotonic() < deadline:
            samples.append(imu.read())
            time.sleep(0.02)

        ok = _report_imu_samples(samples)
        if args.spin_test:
            ok = _run_spin_test(imu, args) and ok
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"[imu] FAIL  read error after {len(samples)} samples: {exc}")
        return False
    finally:
        imu.disconnect()


def _report_imu_samples(samples: list[IMUSample]) -> bool:
    """Print accel/gyro/mag summaries and judge whether the sensor is really live."""
    if not samples:
        print("[imu] FAIL  no samples read")
        return False

    accel_mags = [math.dist((0, 0, 0), s.accel_m_s2) for s in samples]
    gyro_mags = [math.dist((0, 0, 0), s.gyro_rad_s) for s in samples]
    mag_mags = [math.dist((0, 0, 0), s.mag_uT) for s in samples]
    last = samples[-1]

    span_s = (samples[-1].timestamp_ns - samples[0].timestamp_ns) / 1e9
    rate_hz = (len(samples) - 1) / span_s if span_s > 0 else 0.0
    print(f"[imu] {len(samples)} samples over {span_s:.1f}s ({rate_hz:.0f} Hz)")
    print(
        f"[imu] accel  |a|={statistics.mean(accel_mags):.2f} m/s^2  "
        f"xyz=({last.accel_m_s2[0]:+.2f}, {last.accel_m_s2[1]:+.2f}, {last.accel_m_s2[2]:+.2f})"
    )
    print(
        f"[imu] gyro   |w|={statistics.mean(gyro_mags):.4f} rad/s  "
        f"xyz=({last.gyro_rad_s[0]:+.4f}, {last.gyro_rad_s[1]:+.4f}, {last.gyro_rad_s[2]:+.4f})"
    )
    print(
        f"[imu] mag    |m|={statistics.mean(mag_mags):.1f} uT  "
        f"xyz=({last.mag_uT[0]:+.1f}, {last.mag_uT[1]:+.1f}, {last.mag_uT[2]:+.1f})"
    )

    ok = True
    if any(not s.valid for s in samples):
        bad = next(s for s in samples if not s.valid)
        print(f"[imu] FAIL  driver flagged invalid samples: {bad.error}")
        ok = False

    mean_accel = statistics.mean(accel_mags)
    if not ACCEL_MIN_M_S2 <= mean_accel <= ACCEL_MAX_M_S2:
        print(
            f"[imu] FAIL  |accel|={mean_accel:.2f} m/s^2 is not ~9.81 - the accelerometer is "
            "not measuring gravity (bad wiring or wrong device)"
        )
        ok = False

    # A wedged I2C read hands back a byte-identical sample forever; real sensor
    # noise always moves the low bits, so zero variation means a dead feed.
    if len(samples) > 5 and statistics.pstdev(accel_mags) == 0.0 and statistics.pstdev(gyro_mags) == 0.0:
        print("[imu] FAIL  every sample is identical - the I2C read is stuck, not live")
        ok = False

    if statistics.mean(mag_mags) <= 0.0:
        print("[imu] WARN  magnetometer reads zero - the LIS3MDL may not be responding")

    if ok:
        print("[imu] PASS  IMU is connected and producing live, sane motion data")
    return ok


def _run_spin_test(imu: AdafruitLSM6DSOXLIS3MDLIMU, args: argparse.Namespace) -> bool:
    """Integrate the yaw gyro while the operator rotates the robot by hand."""
    print()
    input(
        f"[imu] spin test: press Enter, then rotate the robot ~90 deg over the next "
        f"{args.spin_seconds:.0f}s... "
    )
    yaw_deg = 0.0
    peak_rate = 0.0
    previous_ns = None
    deadline = time.monotonic() + args.spin_seconds
    while time.monotonic() < deadline:
        sample = imu.read()
        if not sample.valid:
            print(f"[imu] FAIL  invalid sample during spin test: {sample.error}")
            return False
        if previous_ns is not None:
            dt = (sample.timestamp_ns - previous_ns) / 1e9
            rate = sample.gyro_rad_s[args.imu_yaw_axis]
            yaw_deg += math.degrees(rate) * dt
            peak_rate = max(peak_rate, abs(math.degrees(rate)))
        previous_ns = sample.timestamp_ns
        time.sleep(0.01)

    print(
        f"[imu] integrated yaw {yaw_deg:+.1f} deg, peak rate {peak_rate:.1f} deg/s "
        f"(gyro axis {args.imu_yaw_axis})"
    )
    if abs(yaw_deg) < 20.0:
        print("[imu] FAIL  the yaw gyro barely moved - wrong axis, or the sensor is not responding")
        return False
    print("[imu] PASS  the yaw gyro tracks rotation")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that the LiDAR and the IMU are working. Run this ON THE PI."
    )
    parser.add_argument("--lidar-port", default=DEFAULT_DEVICE, help="LiDAR serial port.")
    parser.add_argument("--lidar-baud", type=int, default=DEFAULT_BAUDRATE, help="LiDAR serial baud rate.")
    parser.add_argument("--lidar-seconds", type=float, default=5.0, help="How long to listen.")
    parser.add_argument("--skip-lidar", action="store_true", help="Check only the IMU.")

    parser.add_argument("--imu-bus", type=int, default=1, help="I2C bus number.")
    parser.add_argument(
        "--imu-accel-address", type=lambda v: int(v, 0), default=0x6A, help="LSM6DSOX address."
    )
    parser.add_argument("--imu-mag-address", type=lambda v: int(v, 0), default=0x1C, help="LIS3MDL address.")
    parser.add_argument("--imu-seconds", type=float, default=3.0, help="How long to sample.")
    parser.add_argument("--imu-yaw-axis", type=int, default=2, help="Gyro axis used as yaw.")
    parser.add_argument(
        "--spin-test",
        action="store_true",
        help="Interactive: rotate the robot by hand and confirm the yaw gyro tracks it.",
    )
    parser.add_argument("--spin-seconds", type=float, default=8.0, help="Spin test window.")
    parser.add_argument("--skip-imu", action="store_true", help="Check only the LiDAR.")
    args = parser.parse_args()

    results: dict[str, bool] = {}
    if not args.skip_lidar:
        results["lidar"] = check_lidar(args)
    if not args.skip_imu:
        results["imu"] = check_imu(args)

    print()
    print("[check] ==== summary ====")
    for name, ok in results.items():
        print(f"[check] {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

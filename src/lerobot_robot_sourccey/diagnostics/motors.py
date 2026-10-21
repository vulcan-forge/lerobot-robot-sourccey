#!/usr/bin/env python3
"""Electrical roll-call for Sourccey's motors: are all 12 arm servos and the
wheel/actuator drivers accounted for?

Two modes:

**On the Pi (default)** - the real electrical check. Pings every servo ID on both
arm buses and reports which answered, with each one's bus voltage and
temperature; claims every wheel-driver GPIO pin to prove the DC side is wired to
pins that exist and are free; and reads the Z actuator's ADC.

    uv run --no-sync sourccey-check-motors

**From your PC** - a lighter smoke test over the same observation stream the
teleop client uses: it shows what the host is currently reading for all 12
joints, Z, and the wheels.

    uv run --no-sync sourccey-check-motors --remote-ip 192.168.1.237

Expected servo layout (from `sourccey_follower.py`):

    left  arm  /dev/robotLeftArm   IDs 1-6    right arm  /dev/robotRightArm  IDs 7-12
    order: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper

**About the wheels:** the DC motors are driven open-loop through DRV8874 H-bridges
on GPIO PWM - there are no encoders and no current sensing anywhere in this stack,
so their presence CANNOT be measured electrically. What this script verifies is the
Pi side of that path (pins valid, free, and drivable). To confirm a wheel motor
itself is alive, use `--wiggle`, which briefly pulses each one so you can see and
hear it - wheels off the ground first.

Nothing is commanded unless you pass `--wiggle` or `--z-stroke`: the arm buses are opened without
a handshake and closed without touching torque, so no arm is ever driven.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import time

from lerobot.motors.motors_bus import Motor, MotorNormMode
from lerobot_robot_sourccey.motors.retry import SourcceyMotorsBus
from lerobot_robot_sourccey.robots.sourccey.config_sourccey import (
    SourcceyConfig,
    sourccey_dc_motors,
    sourccey_dc_motors_config,
    sourccey_motor_models,
)

from .camera_remote import ObservationSubscriber

# Wiring defaults come from the same package configuration as the robot.
JOINT_ORDER = tuple(sourccey_motor_models())
ARM_IDS = {"left": (1, 2, 3, 4, 5, 6), "right": (7, 8, 9, 10, 11, 12)}
MOTOR_MODELS = sourccey_motor_models()
DEFAULT_LEFT_ARM_PORT = SourcceyConfig.left_arm_port
DEFAULT_RIGHT_ARM_PORT = SourcceyConfig.right_arm_port
DC_CHANNELS = tuple(sourccey_dc_motors())
DC_IN1_PINS = sourccey_dc_motors_config()["in1_pins"]
DC_IN2_PINS = sourccey_dc_motors_config()["in2_pins"]
DC_PWM_FREQUENCY = sourccey_dc_motors_config()["pwm_frequency"]
Z_MINIMUM_COMMAND = SourcceyConfig.z_minimum_up_command

# Feetech servos report bus voltage in 0.1 V units. A 3S/4S pack that has sagged
# below this is browning out even if every servo still answers.
MIN_BUS_VOLTAGE = 9.0
# Sustained temperatures above this mean a servo is straining or failing.
MAX_TEMPERATURE_C = 55.0


def _build_bus(port: str, side: str) -> SourcceyMotorsBus:
    """Build a bus with the same IDs/models the robot itself uses."""
    models = MOTOR_MODELS
    ids = ARM_IDS[side]
    return SourcceyMotorsBus(
        port=port,
        motors={
            name: Motor(ids[i], models[name], MotorNormMode.RANGE_M100_100)
            for i, name in enumerate(JOINT_ORDER)
        },
    )


def check_arm_bus(side: str, port: str) -> bool:
    """Ping every servo on one arm bus and report voltage/temperature."""
    ids = ARM_IDS[side]
    print(f"[arms] ---- {side} arm: {port} (expecting IDs {ids[0]}-{ids[-1]}) ----")

    bus = _build_bus(port, side)
    try:
        # handshake=False: a missing servo must be REPORTED, not turned into a
        # connection error that hides the other five.
        bus.connect(handshake=False)
    except Exception as exc:  # noqa: BLE001 - surface the driver's own message
        print(f"[arms] FAIL  could not open {port}: {exc}")
        print("[arms]       check the USB-serial adapter and `ls -l /dev/robot*`")
        return False

    ok = True
    try:
        found = {motor_id: model for motor_id in ids if (model := bus.ping(motor_id)) is not None}
        print(f"[arms] bus roll-call answered: {sorted(found) if found else '(nobody)'}")

        for index, name in enumerate(JOINT_ORDER):
            motor_id = ids[index]
            model_number = bus.ping(name, num_retry=2)
            if model_number is None:
                print(f"[arms] FAIL  id {motor_id:>2} {name:<14} SILENT - no response on the bus")
                ok = False
                continue

            try:
                voltage = bus.read("Present_Voltage", name, normalize=False) / 10.0
                temperature = float(bus.read("Present_Temperature", name, normalize=False))
                position = bus.read("Present_Position", name, normalize=False)
            except Exception as exc:  # noqa: BLE001
                print(f"[arms] FAIL  id {motor_id:>2} {name:<14} answered ping but reads failed: {exc}")
                ok = False
                continue

            flags = []
            if voltage < MIN_BUS_VOLTAGE:
                flags.append(f"LOW VOLTAGE {voltage:.1f}V")
                ok = False
            if temperature > MAX_TEMPERATURE_C:
                flags.append(f"HOT {temperature:.0f}C")
            suffix = f"  <-- {', '.join(flags)}" if flags else ""
            print(
                f"[arms] PASS  id {motor_id:>2} {name:<14} model={model_number} "
                f"{voltage:.1f}V {temperature:.0f}C pos={position}{suffix}"
            )

        unexpected = sorted(set(found) - set(ids))
        if unexpected:
            print(
                f"[arms] WARN  unexpected IDs on this bus: {unexpected} (duplicate or misassigned servo ID)"
            )
    finally:
        # disable_torque=False: this check never writes to a servo.
        bus.disconnect(disable_torque=False)

    return ok


def check_wheel_drivers(args: argparse.Namespace) -> bool:
    """Verify the DC driver GPIO pins are valid, free, and drivable.

    This is the Pi side of the wheel path only. These motors are open-loop -
    no encoders, no current sense - so a motor that is unplugged at the H-bridge
    looks identical to a healthy one from software. `--wiggle` is the only way to
    confirm the motor itself.
    """
    print()
    print("[wheels] ---- wheel + actuator drivers ----")
    names = list(DC_CHANNELS)
    in1_pins, in2_pins = DC_IN1_PINS, DC_IN2_PINS
    print(f"[wheels] {len(names)} DC channels: {', '.join(names)}")
    print(f"[wheels] IN1 pins {in1_pins}  IN2 pins {in2_pins}  @ {DC_PWM_FREQUENCY} Hz")

    try:
        from gpiozero import PWMLED
    except Exception as exc:  # noqa: BLE001
        print(f"[wheels] FAIL  gpiozero is unavailable: {exc}")
        print("[wheels]       this check only works on the Pi (install the Sourccey robot profile)")
        return False

    ok = True
    for index, name in enumerate(names):
        channels = []
        try:
            for label, pin in (("IN1", in1_pins[index]), ("IN2", in2_pins[index])):
                led = PWMLED(pin, frequency=DC_PWM_FREQUENCY)
                led.value = 0.0  # claimed but idle: this does NOT turn the motor
                channels.append((label, pin, led))
            claimed = ", ".join(f"{label}=GPIO{pin}" for label, pin, _ in channels)
            print(f"[wheels] PASS  {name:<16} driver pins claimed and idle ({claimed})")
        except Exception as exc:  # noqa: BLE001
            print(f"[wheels] FAIL  {name:<16} could not claim its pins: {exc}")
            print("[wheels]       another process (sourccey-host?) already owns this GPIO")
            ok = False
        finally:
            for _label, _pin, led in channels:
                with contextlib.suppress(Exception):
                    led.close()

    print("[wheels] NOTE  DC motors are open-loop (no encoders, no current sense): this")
    print("[wheels]       proves the Pi's driver pins are healthy, NOT that a motor is")
    print("[wheels]       connected. Use --wiggle to confirm the motors themselves.")

    if args.wiggle:
        ok = _wiggle_wheels(args, names, in1_pins, in2_pins, DC_PWM_FREQUENCY) and ok
    return ok


def _wiggle_wheels(
    args: argparse.Namespace,
    names: list[str],
    in1_pins: list[int],
    in2_pins: list[int],
    frequency: int,
) -> bool:
    """Briefly pulse each DC channel so the operator can see/hear it respond."""
    print()
    print("[wiggle] This will BRIEFLY DRIVE each wheel and the linear actuator.")
    print("[wiggle] The robot must be on blocks with its wheels off the ground.")
    answer = input("[wiggle] Type 'yes' to continue: ").strip().lower()
    if answer != "yes":
        print("[wiggle] skipped")
        return True

    from gpiozero import PWMLED

    for index, name in enumerate(names):
        if name == "linear_actuator" and not args.wiggle_actuator:
            print(f"[wiggle] {name:<16} skipped (pass --wiggle-actuator to include it)")
            continue
        in1 = in2 = None
        try:
            in1 = PWMLED(in1_pins[index], frequency=frequency)
            in2 = PWMLED(in2_pins[index], frequency=frequency)
            in2.value = 0.0
            print(
                f"[wiggle] {name:<16} forward at {args.wiggle_duty:.2f} duty "
                f"for {args.wiggle_seconds:.1f}s ..."
            )
            in1.value = args.wiggle_duty
            time.sleep(args.wiggle_seconds)
            in1.value = 0.0
            time.sleep(0.3)
        except Exception as exc:  # noqa: BLE001
            print(f"[wiggle] FAIL  {name}: {exc}")
            return False
        finally:
            for led in (in1, in2):
                if led is not None:
                    with contextlib.suppress(Exception):
                        led.value = 0.0
                        led.close()
    print("[wiggle] done - every channel that moved is electrically alive")
    return True


class ZPotentiometer:
    """Reads the Z actuator's potentiometer straight off the MCP3008.

    Use raw ADC counts for electrical diagnosis without requiring lift
    calibration or starting the robot's actuator control loop.
    """

    RAW_MAX = 1023
    VREF = 3.30

    def __init__(self, channel: int, samples: int = 25) -> None:
        self.channel = int(channel)
        self.samples = max(int(samples), 1)
        self._adc = None

    def connect(self) -> None:
        from gpiozero import MCP3008

        adc = MCP3008(channel=self.channel)
        _ = adc.raw_value  # probe once so a dead SPI bus fails here, not later
        self._adc = adc

    def read(self) -> tuple[int, float]:
        """Return (averaged raw 0-1023, volts)."""
        adc = self._adc
        if adc is None:
            raise RuntimeError("ADC is not connected.")
        total = sum([float(adc.raw_value) for _ in range(self.samples)])
        raw = int(round(total / self.samples))
        return raw, (raw / self.RAW_MAX) * self.VREF

    def close(self) -> None:
        if self._adc is not None:
            with contextlib.suppress(Exception):
                self._adc.close()
            self._adc = None


def check_z_actuator(args: argparse.Namespace) -> bool:
    """Read the Z actuator's potentiometer through the MCP3008 ADC."""
    print()
    print("[z] ---- Z actuator feedback ----")
    sensor = ZPotentiometer(args.z_adc_channel)
    try:
        sensor.connect()
    except ImportError as exc:
        print(f"[z] FAIL  gpiozero is not installed: {exc}")
        print("[z]       this check only runs on the Pi")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"[z] FAIL  MCP3008 on channel {args.z_adc_channel} did not respond: {exc}")
        print("[z]       check SPI is enabled (`raspi-config`) and the ADC wiring")
        return False

    try:
        raw, voltage = sensor.read()
        print(f"[z] PASS  ADC channel {args.z_adc_channel}: raw={raw}/1023 ({voltage:.2f}V)")
        # Both rails mean a floating wiper or a disconnected pot far more often
        # than a genuinely fully-extended actuator.
        if raw <= 2 or raw >= 1021:
            print(
                "[z] WARN  the reading is pinned at a rail - if the actuator is not at "
                "an end stop, the potentiometer is likely disconnected"
            )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[z] FAIL  ADC read failed: {exc}")
        return False
    finally:
        sensor.close()


def check_z_stroke(args: argparse.Namespace) -> bool:
    """Drive the linear actuator briefly and confirm the ADC follows the motion.

    This is the only closed-loop check on the robot: the Z axis has a
    potentiometer, so driving the motor and watching the reading move proves the
    whole chain at once - H-bridge, motor, mechanism, pot, and ADC. If the
    reading does not move, one of those is broken and the printout says which
    direction was tried.
    """
    print()
    print("[z-stroke] ---- linear actuator motion test ----")
    print("[z-stroke] This will BRIEFLY DRIVE the Z axis in both directions.")
    print("[z-stroke] Make sure the column has clearance above and below, and that")
    print("[z-stroke] nothing (arms, cables, people) is in the way.")
    if input("[z-stroke] Type 'yes' to continue: ").strip().lower() != "yes":
        print("[z-stroke] skipped")
        return True

    try:
        from gpiozero import PWMLED
    except Exception as exc:  # noqa: BLE001
        print(f"[z-stroke] FAIL  needs gpiozero on the Pi: {exc}")
        return False

    index = DC_CHANNELS.index("linear_actuator")
    in1_pin, in2_pin = DC_IN1_PINS[index], DC_IN2_PINS[index]
    frequency = DC_PWM_FREQUENCY

    # Few samples per read: the ADC is polled while the column is moving.
    sensor = ZPotentiometer(args.z_adc_channel, samples=5)
    try:
        sensor.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"[z-stroke] FAIL  the Z ADC did not respond, so motion cannot be verified: {exc}")
        return False

    baseline = sensor.read()[0]
    print(f"[z-stroke] baseline ADC reading: {baseline}/1023")

    deltas: dict[str, int] = {}
    try:
        # Direction is intentionally unlabeled: which pin raises the column
        # depends on the motor's wiring, and the test only needs the reading to
        # MOVE. Direction B runs second to bring the column back toward start.
        for label, (drive_pin, idle_pin) in (
            ("A", (in1_pin, in2_pin)),
            ("B", (in2_pin, in1_pin)),
        ):
            start = sensor.read()[0]
            drive = idle = None
            try:
                drive = PWMLED(drive_pin, frequency=frequency)
                idle = PWMLED(idle_pin, frequency=frequency)
                idle.value = 0.0
                drive.value = args.z_duty
                deadline = time.monotonic() + args.z_seconds
                reading = start
                while time.monotonic() < deadline:
                    time.sleep(0.05)
                    reading = sensor.read()[0]
                    # A rail means an end stop: stop pushing into it.
                    if reading <= 2 or reading >= 1021:
                        print(f"[z-stroke] direction {label}: hit an end stop at {reading}, stopping")
                        break
            finally:
                for led in (drive, idle):
                    if led is not None:
                        with contextlib.suppress(Exception):
                            led.value = 0.0
                            led.close()
            time.sleep(0.4)  # let the column settle before reading
            settled = sensor.read()[0]
            deltas[label] = settled - start
            print(f"[z-stroke] direction {label}: {start} -> {settled} (delta {settled - start:+d} counts)")
    finally:
        sensor.close()

    best = max(abs(d) for d in deltas.values()) if deltas else 0
    if best < args.z_min_delta:
        print(
            f"[z-stroke] FAIL  the ADC moved at most {best} counts (need {args.z_min_delta}) - "
            "the actuator is not moving, or the pot is not tracking it"
        )
        print("[z-stroke]       if it was already at an end stop, reposition it and re-run;")
        print(f"[z-stroke]       otherwise check the H-bridge on GPIO{in1_pin}/GPIO{in2_pin}, the")
        print("[z-stroke]       actuator's power, and the potentiometer wiring")
        return False
    if any(d > 0 for d in deltas.values()) and any(d < 0 for d in deltas.values()):
        print(
            f"[z-stroke] PASS  the actuator drives both ways and the ADC follows (best delta {best} counts)"
        )
    else:
        print(
            f"[z-stroke] WARN  the ADC moved {best} counts but not in both directions - "
            "one direction may be blocked, at an end stop, or miswired"
        )
    return True


def check_remote(args: argparse.Namespace) -> bool:
    """From the PC: report what the host is reading for every motor."""
    print("[remote] ---- motor telemetry from the robot host ----")
    subscriber = ObservationSubscriber(args.remote_ip, args.port, connect_timeout_s=args.connect_timeout)
    print(f"[remote] connecting to {subscriber.endpoint} (passive: observations only)")
    try:
        subscriber.connect()
    except TimeoutError as exc:
        print(f"[remote] FAIL  {exc}")
        print("[remote]       start it on the Pi with: uv run sourccey-host")
        return False

    try:
        # Let a few packets land so a joint that only intermittently reads shows up.
        time.sleep(args.remote_seconds)
        state = subscriber.state()
    finally:
        subscriber.close()

    ok = True
    for side in ("left", "right"):
        ids = ARM_IDS[side]
        for index, joint in enumerate(JOINT_ORDER):
            key = f"{side}_{joint}.pos"
            if key not in state or not math.isfinite(state[key]):
                print(
                    f"[remote] FAIL  id {ids[index]:>2} {key:<26} missing or unavailable in the observation"
                )
                ok = False
            else:
                print(f"[remote] PASS  id {ids[index]:>2} {key:<26} {state[key]:+.2f}")

    for key in ("z.pos", "x.vel", "y.vel", "theta.vel"):
        if key in state and math.isfinite(state[key]):
            print(f"[remote] ----  {key:<32} {state[key]:+.2f}")
        else:
            print(f"[remote] FAIL  {key:<32} missing or unavailable in the observation")
            ok = False

    print("[remote] NOTE  this shows what the HOST can read. Base velocities are the")
    print("[remote]       commanded values (the DC motors have no encoders), and a servo")
    print("[remote]       that dropped off the bus can still show its last value - run")
    print("[remote]       this script ON THE PI for a true electrical roll-call.")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Roll-call for the 12 arm servos, the wheel drivers, and the Z actuator."
    )
    parser.add_argument(
        "--remote-ip",
        default=None,
        help="Run the lighter PC-side check against a robot host instead of the local buses.",
    )
    parser.add_argument("--port", type=int, default=5556, help="Host observation port (remote mode).")
    parser.add_argument(
        "--connect-timeout", type=float, default=10.0, help="Remote connect timeout in seconds."
    )
    parser.add_argument(
        "--remote-seconds", type=float, default=2.0, help="Remote sampling window in seconds."
    )

    parser.add_argument("--left-port", default=DEFAULT_LEFT_ARM_PORT, help="Left arm serial port.")
    parser.add_argument("--right-port", default=DEFAULT_RIGHT_ARM_PORT, help="Right arm serial port.")
    parser.add_argument("--skip-arms", action="store_true", help="Skip the arm servo roll-call.")
    parser.add_argument("--skip-wheels", action="store_true", help="Skip the DC driver check.")
    parser.add_argument("--skip-z", action="store_true", help="Skip the Z actuator ADC read.")
    parser.add_argument("--z-adc-channel", type=int, default=1, help="MCP3008 channel for Z.")

    parser.add_argument(
        "--wiggle",
        action="store_true",
        help="Briefly drive each wheel so you can confirm the motors respond (asks first).",
    )
    parser.add_argument(
        "--wiggle-actuator",
        action="store_true",
        help="Include the linear actuator in --wiggle (excluded by default).",
    )
    parser.add_argument("--wiggle-duty", type=float, default=0.35, help="Wiggle PWM duty (0-1).")
    parser.add_argument("--wiggle-seconds", type=float, default=0.6, help="Wiggle duration per motor.")

    parser.add_argument(
        "--z-stroke",
        action="store_true",
        help="Drive the linear actuator both ways and confirm the ADC follows (asks first).",
    )
    parser.add_argument(
        "--z-duty",
        type=float,
        default=Z_MINIMUM_COMMAND,
        help="PWM duty for --z-stroke; below the configured minimum the column will not move.",
    )
    parser.add_argument("--z-seconds", type=float, default=1.0, help="Drive time per direction.")
    parser.add_argument(
        "--z-min-delta",
        type=int,
        default=15,
        help="Raw ADC counts the reading must move for --z-stroke to pass.",
    )
    args = parser.parse_args()

    results: dict[str, bool] = {}
    if args.remote_ip:
        results["host telemetry"] = check_remote(args)
    else:
        if not args.skip_arms:
            results["left arm (ids 1-6)"] = check_arm_bus("left", args.left_port)
            print()
            results["right arm (ids 7-12)"] = check_arm_bus("right", args.right_port)
        if not args.skip_wheels:
            results["wheel drivers"] = check_wheel_drivers(args)
        if not args.skip_z:
            results["z actuator"] = check_z_actuator(args)
        if args.z_stroke:
            results["z actuator motion"] = check_z_stroke(args)

    print()
    print("[check] ==== summary ====")
    for name, ok in results.items():
        print(f"[check] {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

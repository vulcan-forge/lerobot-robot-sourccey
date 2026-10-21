from __future__ import annotations

import importlib
import os
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.request import urlopen

import numpy as np
import pytest
from lerobot_robot_sourccey.diagnostics import (
    camera_devices,
    camera_remote,
    lidar_imu,
    motors,
    preview,
)
from lerobot_robot_sourccey.motors.retry import MotorRetryPolicy, SourcceyMotorsBus
from lerobot_robot_sourccey.robots.protobuf.sourccey_protobuf import SourcceyProtobuf
from lerobot_robot_sourccey.robots.sourccey.config_sourccey import (
    SourcceyConfig,
    sourccey_cameras_config,
    sourccey_dc_motors_config,
    sourccey_motor_models,
)
from lerobot_robot_sourccey.sensors.imu import IMUSample
from lerobot_robot_sourccey.sensors.lidar.ld19 import crc8

COMMANDS = (
    "eye-cameras",
    "arm-cameras",
    "eye-cameras-local",
    "arm-cameras-local",
    "bottom-camera",
    "motors",
    "lidar-imu",
)


@pytest.mark.parametrize("suffix", COMMANDS)
def test_installed_command_help_outside_checkout(suffix: str, tmp_path: Path) -> None:
    command = Path(sys.executable).parent / ("sourccey-check-" + suffix + (".exe" if os.name == "nt" else ""))
    result = subprocess.run(
        [str(command), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


@pytest.mark.parametrize(
    "name,extra,expected",
    [
        ("eye_cameras", ["--remote-ip", "127.0.0.1", "--skip-bottom"], ("front_left", "front_right")),
        (
            "eye_cameras",
            ["--remote-ip", "127.0.0.1", "--bottom-key", "underside"],
            ("front_left", "front_right", "underside"),
        ),
        ("arm_cameras", ["--remote-ip", "127.0.0.1"], ("wrist_left", "wrist_right")),
    ],
)
def test_remote_camera_commands_route_keys_and_return_status(monkeypatch, name, extra, expected):
    module = importlib.import_module("lerobot_robot_sourccey.diagnostics." + name)
    run = Mock(return_value=7)
    monkeypatch.setattr(module, "run_camera_check", run)
    monkeypatch.setattr(sys, "argv", [name, *extra])
    assert module.main() == 7
    assert run.call_args.args[0] == expected
    assert run.call_args.args[1][expected[0]] == 30


@pytest.mark.parametrize(
    "name,extra,expected",
    [
        ("eye_cameras_local", [], ("front_left", "front_right")),
        ("eye_cameras_local", ["--include-bottom"], ("front_left", "front_right", "bottom")),
        ("arm_cameras_local", [], ("wrist_left", "wrist_right")),
    ],
)
def test_local_camera_commands_use_package_defaults(monkeypatch, name, extra, expected):
    module = importlib.import_module("lerobot_robot_sourccey.diagnostics." + name)
    run = Mock(return_value=1)
    monkeypatch.setattr(module, "run_device_check", run)
    monkeypatch.setattr(camera_devices.os.path, "exists", lambda path: True)
    monkeypatch.setattr(sys, "argv", [name, *extra])
    assert module.main() == 1
    specs = run.call_args.args[0]
    assert tuple(spec.key for spec in specs) == expected
    for spec in specs:
        assert spec.path == camera_devices.CAMERA_DEVICES[spec.key]
        assert (spec.width, spec.height, spec.fps) == (320, 240, 30)


def test_local_camera_overrides_and_canonical_bottom_alias():
    args = camera_devices.build_parser("test").parse_args(
        [
            "--device",
            "front_left=/dev/video9",
            "--width",
            "640",
            "--fps",
            "15",
        ]
    )
    spec = camera_devices.specs_for(("front_left",), args)[0]
    assert (spec.path, spec.width, spec.fps) == ("/dev/video9", 640, 15)
    assert camera_devices.CAMERA_DEVICES["bottom"] == "/dev/cameraFrontBottom"
    assert camera_devices.CAMERA_DEVICES["front_left"] == str(
        sourccey_cameras_config()["front_left"].index_or_path
    )
    args.device = ["unknown=/dev/video1"]
    with pytest.raises(KeyError, match="unknown camera"):
        camera_devices.specs_for(("front_left",), args)


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"frames": 0}, "FAIL"),
        ({"blank_frames": 20}, "FAIL"),
        ({"frozen_frames": 19}, "FAIL"),
        ({"blank_frames": 1}, "WARN"),
        ({}, "PASS"),
    ],
)
def test_local_and_remote_camera_health_verdicts(changes, expected):
    worker = camera_devices.CameraWorker(camera_devices.CameraSpec("eye", "test", 320, 240, 30))
    worker.stats.opened = True
    worker.stats.frames = 20
    worker.stats.stamps.extend([0.0, 1 / 30])
    remote = camera_remote.CameraStats(frames=20, last_rx=camera_remote.time.monotonic())
    remote.stamps.extend([0.0, 1 / 30])
    for key, value in changes.items():
        setattr(worker.stats, key, value)
        setattr(remote, key, value)
    assert worker.verdict()[0] == expected
    assert camera_remote.verdict_for("eye", remote, 30)[0] == expected


def test_remote_camera_staleness_and_real_protobuf_ingestion():
    receiver = camera_remote.ObservationSubscriber("127.0.0.1", 5556)
    frame = np.arange(16 * 16 * 3, dtype=np.uint8).reshape(16, 16, 3)
    payload = (
        SourcceyProtobuf().observation_to_protobuf({"front_left": frame, "z.pos": 42.0}).SerializeToString()
    )
    receiver._ingest(payload)
    assert receiver.packets() == 1
    assert receiver.published_keys() == ["front_left"]
    assert receiver.state()["z.pos"] == 42
    assert receiver.latest("front_left").shape == frame.shape
    stats = receiver.stats("front_left")
    stats.last_rx -= camera_remote.STALE_AFTER_S + 1
    assert camera_remote.verdict_for("front_left", stats, 30)[0] == "FAIL"
    receiver.close()


def test_camera_open_failure_releases_capture(monkeypatch):
    capture = Mock(isOpened=Mock(return_value=False))
    monkeypatch.setattr(camera_devices.cv2, "VideoCapture", Mock(return_value=capture))
    worker = camera_devices.CameraWorker(camera_devices.CameraSpec("eye", "test", 320, 240, 30))
    assert not worker.open()
    capture.release.assert_called_once()
    assert worker.verdict()[0] == "FAIL"


def test_local_worker_marks_failed_reads_dead_and_releases(monkeypatch):
    monkeypatch.setattr(camera_devices, "MAX_CONSECUTIVE_READ_FAILURES", 2)
    monkeypatch.setattr(camera_devices.time, "sleep", lambda seconds: None)
    worker = camera_devices.CameraWorker(camera_devices.CameraSpec("eye", "test", 320, 240, 30))
    capture = Mock(read=Mock(return_value=(False, None)))
    worker._cap = capture
    worker.stats.opened = True
    worker.start()
    worker.join(timeout=1)
    worker.stop()
    assert not worker.is_alive()
    assert worker.stats.dead
    assert worker.verdict()[0] == "FAIL"
    capture.release.assert_called_once()


def test_shared_preview_serves_jpeg_and_stops():
    server = preview.MjpegServer(0, "Check")
    server.publish(np.zeros((8, 8, 3), dtype=np.uint8))
    server.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.port}/", timeout=2) as response:
            assert b"stream.mjpg" in response.read()
        assert server._jpeg.startswith(b"\xff\xd8")
    finally:
        server.stop()
    assert not server._thread.is_alive()
    assert server._stop_event.is_set()


def test_motor_defaults_and_retry_policy_match_robot():
    assert motors.MOTOR_MODELS == sourccey_motor_models()
    assert motors.DC_IN1_PINS == sourccey_dc_motors_config()["in1_pins"]
    assert motors.DC_IN2_PINS == sourccey_dc_motors_config()["in2_pins"]
    assert motors.Z_MINIMUM_COMMAND == SourcceyConfig.z_minimum_up_command
    for side in ("left", "right"):
        bus = motors._build_bus("test", side)
        assert isinstance(bus, SourcceyMotorsBus)
        assert bus.retry_policy == MotorRetryPolicy()
        assert tuple(motor.id for motor in bus.motors.values()) == motors.ARM_IDS[side]


@pytest.mark.parametrize("fault", [None, "silent", "voltage", "read"])
def test_arm_bus_checks_are_read_only_and_disconnect(monkeypatch, fault):
    bus = Mock()
    bus.ping.return_value = None if fault == "silent" else 777

    def read(register, name, **kwargs):
        if fault == "read":
            raise ConnectionError("lost motor")
        return {
            "Present_Voltage": 80 if fault == "voltage" else 120,
            "Present_Temperature": 30,
            "Present_Position": 2048,
        }[register]

    bus.read.side_effect = read
    monkeypatch.setattr(motors, "_build_bus", lambda *args: bus)
    assert motors.check_arm_bus("left", "test") is (fault is None)
    bus.connect.assert_called_once_with(handshake=False)
    bus.disconnect.assert_called_once_with(disable_torque=False)
    bus.write.assert_not_called()
    bus.sync_write.assert_not_called()


def test_motor_and_sensor_commands_aggregate_failures(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["motors"])
    monkeypatch.setattr(motors, "check_arm_bus", Mock(side_effect=[True, False]))
    monkeypatch.setattr(motors, "check_wheel_drivers", Mock(return_value=True))
    monkeypatch.setattr(motors, "check_z_actuator", Mock(return_value=True))
    motion = Mock()
    monkeypatch.setattr(motors, "check_z_stroke", motion)
    assert motors.main() == 1
    motion.assert_not_called()
    monkeypatch.setattr(sys, "argv", ["sensors"])
    monkeypatch.setattr(lidar_imu, "check_lidar", Mock(return_value=True))
    monkeypatch.setattr(lidar_imu, "check_imu", Mock(return_value=False))
    assert lidar_imu.main() == 1


def test_wiggle_decline_does_not_open_gpio(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda message: "no")
    assert motors._wiggle_wheels(SimpleNamespace(), [], [], [], 10000)


def packet_bytes():
    packet = bytearray((0x54, 0x2C))
    packet.extend(struct.pack("<HH", 3600, 0))
    for _ in range(12):
        packet.extend(struct.pack("<HB", 1000, 200))
    packet.extend(struct.pack("<HH", 1100, 1))
    packet.append(crc8(packet))
    return bytes(packet)


@pytest.mark.parametrize("corrupt,expected", [(False, True), (True, False)])
def test_lidar_check_uses_validated_packets_and_closes_serial(monkeypatch, corrupt, expected):
    import serial

    payload = bytearray(packet_bytes())
    if corrupt:
        payload[8] ^= 1
    port = Mock(in_waiting=len(payload), read=Mock(return_value=bytes(payload)))
    monkeypatch.setattr(serial, "Serial", Mock(return_value=port))
    monkeypatch.setattr(lidar_imu.os.path, "exists", lambda path: True)
    clock = Mock(side_effect=[0, 0.1, 2])
    monkeypatch.setattr(lidar_imu, "time", SimpleNamespace(monotonic=clock))
    args = SimpleNamespace(lidar_port="test", lidar_baud=230400, lidar_seconds=1)
    assert lidar_imu.check_lidar(args) is expected
    port.close.assert_called_once()


@pytest.mark.parametrize("valid", [True, False])
def test_imu_uses_package_backend_and_disconnects(monkeypatch, valid):
    imu = Mock()
    imu.read.return_value = IMUSample(
        timestamp_ns=1,
        accel_m_s2=(0, 0, 9.81),
        gyro_rad_s=(0, 0, 0),
        mag_uT=(20, 0, 0),
        valid=valid,
    )
    backend = Mock(return_value=imu)
    monkeypatch.setattr(lidar_imu, "AdafruitLSM6DSOXLIS3MDLIMU", backend)
    monkeypatch.setattr(
        lidar_imu, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 0.1, 2]), sleep=Mock())
    )
    args = SimpleNamespace(
        imu_bus=1, imu_accel_address=0x6A, imu_mag_address=0x1C, imu_seconds=1, spin_test=False
    )
    assert lidar_imu.check_imu(args) is valid
    assert backend.call_args.args[0].lsm6dsox_address == 0x6A
    imu.disconnect.assert_called_once()


def test_bottom_camera_udev_rules_use_package_alias():
    module = importlib.import_module("lerobot_robot_sourccey.diagnostics.bottom_camera")
    rule = module.udev_rule_for("1-1.2", "cameraFrontBottom")
    assert 'SYMLINK+="cameraFrontBottom"' in rule
    assert 'KERNELS=="1-1.2"' in rule
    assert 'ATTR{index}=="0"' in rule

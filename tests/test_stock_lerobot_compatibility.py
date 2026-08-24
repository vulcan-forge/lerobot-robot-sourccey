from pathlib import Path

import pytest

from lerobot_robot_sourccey import (
    Sourccey,
    SourcceyClient,
    SourcceyClientConfig,
    SourcceyConfig,
    SourcceyTeleoperator,
    SourcceyTeleoperatorConfig,
)
from lerobot_robot_sourccey.battery import BatteryData
from lerobot_robot_sourccey.robots.protobuf.sourccey_protobuf import SourcceyProtobuf
from lerobot_robot_sourccey.sensors.imu import IMUConfig, IMUSample
import lerobot_robot_sourccey.robots.sourccey_z_actuator.sourccey_z_actuator as z_module


def make_teleoperator(tmp_path: Path) -> SourcceyTeleoperator:
    return SourcceyTeleoperator(
        SourcceyTeleoperatorConfig(
            calibration_dir=tmp_path,
            left_arm_port="left",
            right_arm_port="right",
            enable_keyboard=False,
        )
    )


def test_stock_opencv_config_can_be_constructed() -> None:
    config = SourcceyConfig()
    assert set(config.cameras) == {"front_left", "front_right", "wrist_left", "wrist_right"}


def test_robot_and_client_construct_with_stock_lerobot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(z_module, "HF_LEROBOT_CALIBRATION", tmp_path)
    robot = Sourccey(SourcceyConfig(calibration_dir=tmp_path, cameras={}))
    client = SourcceyClient(
        SourcceyClientConfig(remote_ip="127.0.0.1", calibration_dir=tmp_path, cameras={})
    )
    assert "left_shoulder_pan.pos" in robot.action_features
    assert "right_shoulder_pan.pos" in robot.action_features
    assert "z.vel" in robot.action_features
    assert "z.vel" in client.action_features


def test_composite_teleoperator_maps_keyboard_actions(tmp_path: Path) -> None:
    teleop = make_teleoperator(tmp_path)
    action = teleop._base_action({"w", "a", "z", "q"})
    assert action["x.vel"] == pytest.approx(0.9)
    assert action["y.vel"] == pytest.approx(0.9)
    assert action["theta.vel"] == pytest.approx(0.9)
    assert action["z.vel"] == pytest.approx(1.0)


def test_base_kinematics_match_installed_wasd_directions() -> None:
    robot = object.__new__(Sourccey)

    forward = robot._body_to_wheel_normalized(x=1.0, y=0.0, theta=0.0)
    assert forward == {
        "front_left": 1.0,
        "front_right": -1.0,
        "rear_left": 1.0,
        "rear_right": -1.0,
    }

    left = robot._body_to_wheel_normalized(x=0.0, y=1.0, theta=0.0)
    assert left == {
        "front_left": -1.0,
        "front_right": -1.0,
        "rear_left": 1.0,
        "rear_right": 1.0,
    }

    assert robot._wheel_normalized_to_body(forward)["x.vel"] == pytest.approx(1.0)
    assert robot._wheel_normalized_to_body(left)["y.vel"] == pytest.approx(1.0)


def test_composite_teleoperator_uses_edges_for_toggles(tmp_path: Path) -> None:
    teleop = make_teleoperator(tmp_path)
    first = teleop._base_action({"n"})
    teleop._previous_keys = {"n"}
    held = teleop._base_action({"n"})
    teleop._previous_keys = set()
    second = teleop._base_action({"n"})
    assert first["untorque_left"] is True
    assert held["untorque_left"] is True
    assert second["untorque_left"] is False


def test_z_velocity_survives_protobuf_round_trip() -> None:
    converter = SourcceyProtobuf()
    message = converter.action_to_protobuf({"z.vel": -0.75})
    action = converter.protobuf_to_action(message)
    assert action["z.vel"] == pytest.approx(-0.75)
    assert "z.pos" not in action


def test_sensor_and_battery_types_are_package_owned() -> None:
    assert IMUConfig.__module__.startswith("lerobot_robot_sourccey")
    assert IMUSample.__module__.startswith("lerobot_robot_sourccey")
    assert BatteryData.__module__.startswith("lerobot_robot_sourccey")

from __future__ import annotations

import pytest

from lerobot_robot_sourccey.robots.protobuf.sourccey_protobuf import SourcceyProtobuf
from lerobot_robot_sourccey.robots.sourccey.sourccey import Sourccey


def test_action_uses_dev12_full_message_format() -> None:
    converter = SourcceyProtobuf()
    message = converter.action_to_protobuf({"x.vel": 0.2, "right_gripper.pos": 42.0})
    decoded = converter.protobuf_to_action(message)

    assert not hasattr(message, "protocol_version")
    assert not hasattr(message, "update_fields")
    assert message.HasField("left_arm_target_joints")
    assert message.HasField("right_arm_target_joints")
    assert message.HasField("base_target_velocity")
    assert decoded["x.vel"] == pytest.approx(0.2)
    assert decoded["right_gripper.pos"] == pytest.approx(42.0)
    assert decoded["left_shoulder_pan.pos"] == pytest.approx(0.0)


def test_dev12_format_preserves_optional_z_presence() -> None:
    message = SourcceyProtobuf().action_to_protobuf({"x.vel": 0.2})

    assert not message.HasField("base_target_position")
    with_z = SourcceyProtobuf().action_to_protobuf({"z.pos": -25.0})
    assert with_z.HasField("base_target_position")


def test_observation_uses_dev12_schema_without_version_field() -> None:
    message = SourcceyProtobuf().observation_to_protobuf({})

    assert not hasattr(message, "protocol_version")


class _FakeBus:
    def __init__(self) -> None:
        self.enabled = 0
        self.disabled = 0

    def enable_torque(self) -> None:
        self.enabled += 1

    def disable_torque(self) -> None:
        self.disabled += 1


class _FakeArm:
    is_connected = True

    def __init__(self) -> None:
        self.bus = _FakeBus()
        self.actions: list[dict[str, float]] = []

    def send_action(self, action):
        self.actions.append(dict(action))
        return dict(action)


class _FakeDCMotors:
    def __init__(self) -> None:
        self.actions: list[dict[str, float]] = []

    def set_velocities(self, action) -> None:
        self.actions.append(dict(action))


class _FakeZActuator:
    use_z_actuator = False


def _physical_robot_stub() -> Sourccey:
    robot = object.__new__(Sourccey)
    robot.left_arm = _FakeArm()
    robot.right_arm = _FakeArm()
    robot.dc_motors_controller = _FakeDCMotors()
    robot.z_actuator = _FakeZActuator()
    robot.untorque_left_prev = False
    robot.untorque_right_prev = False
    robot._last_base_goal_vel = {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}
    return robot


def test_physical_robot_merges_partial_base_axes() -> None:
    robot = _physical_robot_stub()

    robot.send_action({"y.vel": 0.5})
    robot.send_action({"x.vel": 0.25})

    assert robot._last_base_goal_vel == {
        "x.vel": pytest.approx(0.25),
        "y.vel": pytest.approx(0.5),
        "theta.vel": pytest.approx(0.0),
    }
    assert len(robot.dc_motors_controller.actions) == 2


def test_arm_only_patch_does_not_touch_base() -> None:
    robot = _physical_robot_stub()

    sent = robot.send_action({"left_shoulder_pan.pos": 12.0})

    assert sent["left_shoulder_pan.pos"] == pytest.approx(12.0)
    assert robot.left_arm.actions == [{"shoulder_pan.pos": 12.0}]
    assert robot.dc_motors_controller.actions == []


def test_omitted_untorque_flag_preserves_current_state() -> None:
    robot = _physical_robot_stub()
    robot.untorque_left_prev = True

    filtered = robot.apply_untorque_flags(
        {"left_shoulder_pan.pos": 12.0, "right_shoulder_pan.pos": 8.0}
    )

    assert "left_shoulder_pan.pos" not in filtered
    assert filtered["right_shoulder_pan.pos"] == pytest.approx(8.0)
    assert robot.left_arm.bus.enabled == 0
    assert robot.untorque_left_prev is True

    robot.apply_untorque_flags({"untorque_left": False})
    assert robot.left_arm.bus.enabled == 1
    assert robot.untorque_left_prev is False

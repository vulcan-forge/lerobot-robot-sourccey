from types import SimpleNamespace
from unittest.mock import Mock
import math

import pytest

from lerobot_robot_sourccey.robots.sourccey.sourccey import Sourccey


def make_robot(left, right, strict=False):
    robot = object.__new__(Sourccey)
    robot.id = "test"
    robot.config = SimpleNamespace(allow_partial_connection=not strict)
    robot._connected = False
    robot._connected_cameras = set()
    robot.cameras = {}
    robot.untorque_left_prev = robot.untorque_right_prev = False
    robot._last_base_goal_vel = {"x.vel": 0., "y.vel": 0., "theta.vel": 0.}
    robot._last_known_z_pos = 0.
    for name, available in (("left", left), ("right", right)):
        arm = Mock()
        arm.is_connected = False
        arm.bus.is_connected = False
        arm.bus.motors = {"shoulder_pan": object()}
        def connect(calibrate, arm=arm, available=available):
            if not available:
                raise ConnectionError("missing port")
            arm.is_connected = True
        arm.connect.side_effect = connect
        arm.get_observation.return_value = {"shoulder_pan.pos": 12.}
        arm.send_action.side_effect = lambda action: dict(action)
        setattr(robot, f"{name}_arm", arm)
    robot.dc_motors_controller = Mock()
    robot.dc_motors_controller.get_velocities.return_value = dict.fromkeys(
        ("front_left", "front_right", "rear_left", "rear_right"), 0.)
    robot.z_actuator = Mock()
    robot.z_actuator.use_z_actuator = True
    robot.z_actuator.read_position.return_value = 3.
    return robot


@pytest.mark.parametrize("left,right", [(True, True), (True, False), (False, True), (False, False)])
def test_optional_arm_lifecycle(left, right):
    robot = make_robot(left, right)
    robot.connect(calibrate=False)
    assert robot.is_connected
    assert robot.available_arms == {"left": left, "right": right}
    obs = robot.get_observation()
    assert obs["z.pos"] == 3.
    for name, available in (("left", left), ("right", right)):
        assert (obs[f"{name}_shoulder_pan.pos"] == 12.) if available else math.isnan(obs[f"{name}_shoulder_pan.pos"])
    sent = robot.send_action({"left_shoulder_pan.pos": 5., "right_shoulder_pan.pos": 6., "x.vel": .2, "z.pos": 4.})
    assert ("left_shoulder_pan.pos" in sent) == left
    assert ("right_shoulder_pan.pos" in sent) == right
    robot.dc_motors_controller.set_velocities.assert_called_once()
    robot.z_actuator.move_to_position.assert_called_once()
    robot.apply_untorque_flags({"untorque_left": True, "untorque_right": True})
    robot.configure()
    robot.calibrate()
    robot.disable_arm_torque()
    for name, available in (("left", left), ("right", right)):
        arm = getattr(robot, f"{name}_arm")
        assert arm.send_action.call_count == int(available)
        assert arm.configure.call_count == int(available)
        assert arm.calibrate.call_count == int(available)
        assert arm.bus.disable_torque.call_count == 2 * int(available)
    robot.disconnect()
    assert not robot.is_connected
    assert robot.left_arm.disconnect.call_count == int(left)
    assert robot.right_arm.disconnect.call_count == int(right)


def test_strict_connection_still_raises_and_cleans_up():
    robot = make_robot(True, False, strict=True)
    with pytest.raises(ConnectionError):
        robot.connect()
    assert not robot.is_connected
    robot.left_arm.disconnect.assert_called_once()


def test_selected_missing_arm_calibration_fails_clearly():
    robot = make_robot(False, False)
    robot.connect()
    with pytest.raises(ConnectionError, match="Left arm is unavailable"):
        robot.auto_calibrate(arm="left")


def test_failed_arm_read_does_not_discard_base_observation():
    robot = make_robot(True, True)
    robot.connect()
    robot.left_arm.get_observation.side_effect = OSError("lost communication")
    obs = robot.get_observation()
    assert math.isnan(obs["left_shoulder_pan.pos"])
    assert obs["right_shoulder_pan.pos"] == 12.
    assert obs["z.pos"] == 3.


def test_no_arms_auto_calibration_still_calibrates_z():
    robot = make_robot(False, False)
    robot.connect()
    robot.z_actuator.calibrator.auto_calibrate.return_value = None
    robot.auto_calibrate()
    robot.z_actuator.calibrator.auto_calibrate.assert_called_once()
    robot.left_arm.auto_calibrate.assert_not_called()
    robot.right_arm.auto_calibrate.assert_not_called()


def test_arm_command_failure_does_not_block_base_or_other_arm():
    robot = make_robot(True, True)
    robot.connect()
    robot.left_arm.send_action.side_effect = OSError("lost communication")
    sent = robot.send_action({"left_shoulder_pan.pos": 5., "right_shoulder_pan.pos": 6., "x.vel": .2})
    assert "left_shoulder_pan.pos" not in sent
    assert sent["right_shoulder_pan.pos"] == 6.
    robot.dc_motors_controller.set_velocities.assert_called_once()

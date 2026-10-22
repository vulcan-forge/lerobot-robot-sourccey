"""Offline arithmetic and calibration integration; never opens a motor bus."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lerobot.motors.motors_bus import MotorCalibration

from lerobot_robot_sourccey.robots.sourccey.config_sourccey import SourcceyConfig
from lerobot_robot_sourccey.robots.sourccey_follower.shoulder_calibration_frame import (
    center_right_shoulder_frame,
)
from lerobot_robot_sourccey.robots.sourccey_follower.config_sourccey_follower import (
    SourcceyFollowerConfig,
)
from lerobot_robot_sourccey.robots.sourccey_follower.sourccey_follower_calibrator import (
    SourcceyFollowerCalibrator,
)


def calibration(offset=791, low=295, high=4037):
    return MotorCalibration(
        id=8, drive_mode=1, homing_offset=offset, range_min=low, range_max=high
    )


def test_frame_is_calculated_from_this_robots_range_and_is_idempotent():
    original = calibration()
    centered = center_right_shoulder_frame(original)
    assert centered == calibration(910, 176, 3918)
    assert original == calibration()
    assert center_right_shoulder_frame(centered) == centered


def test_different_robot_alignment_selects_a_different_offset():
    first = center_right_shoulder_frame(calibration(791, 295, 4037))
    second = center_right_shoulder_frame(calibration(500, 295, 4037))
    assert first.homing_offset == 910
    assert second.homing_offset == 619
    assert (
        (first.range_min, first.range_max)
        == (second.range_min, second.range_max)
        == (176, 3918)
    )


@pytest.mark.parametrize(
    "offset,low,high",
    [(791, 295, 4037), (791, 296, 4095), (900, 500, 3500), (-2047, 3500, 4000)],
)
def test_every_tick_preserves_physical_angle_and_normalization(offset, low, high):
    original = calibration(offset, low, high)
    centered = center_right_shoulder_frame(original)
    assert centered.range_max - centered.range_min == high - low
    assert abs(centered.range_min - (4095 - centered.range_max)) <= 1
    for raw in range(low, high + 1):
        new_raw = centered.range_min + raw - low
        assert (raw + offset) % 4096 == (new_raw + centered.homing_offset) % 4096
        assert (raw - low) / (high - low) == (new_raw - centered.range_min) / (
            centered.range_max - centered.range_min
        )


def test_unrepresentable_half_turn_offset_uses_nearest_safe_frame():
    centered = center_right_shoulder_frame(calibration(1929, 295, 4037))
    assert centered == calibration(2047, 177, 3919)
    assert min(centered.range_min, 4095 - centered.range_max) == 176


@pytest.mark.parametrize(
    "offset,low,high",
    [
        (791, 0, 4095),
        (-2047, 0, 4093),
        (791, 4000, 20),
        (2048, 295, 4037),
        (791, 1, 1),
    ],
)
def test_invalid_or_seam_filling_range_rejected(offset, low, high):
    with pytest.raises(ValueError):
        center_right_shoulder_frame(calibration(offset, low, high))


def make_robot(tmp_path, orientation="right", protect=True):
    bus = SimpleNamespace(
        motors={"shoulder_lift": SimpleNamespace(id=8, model="sts3250")},
        disable_torque=Mock(),
        write_calibration=Mock(),
    )
    return SimpleNamespace(
        config=SimpleNamespace(
            orientation=orientation,
            protect_right_shoulder_encoder_seam=protect,
        ),
        bus=bus,
        calibration_fpath=tmp_path / f"sourccey_{orientation}.json",
        calibration={},
        is_calibrated=True,
        id=f"sourccey_{orientation}",
        _save_calibration=Mock(),
    )


def test_protection_configuration_defaults_to_enabled():
    follower = SourcceyFollowerConfig(port="unused", cameras={})
    whole_robot = SourcceyConfig(cameras={})
    assert follower.protect_right_shoulder_encoder_seam is True
    assert whole_robot.right_arm_protect_shoulder_encoder_seam is True


@pytest.mark.parametrize("full", [False, True])
def test_both_auto_paths_write_and_save_automatically_centered_calibration(
    tmp_path, full
):
    robot = make_robot(tmp_path)
    calibrator = SourcceyFollowerCalibrator(robot)
    calibrator._initialize_calibration = Mock(return_value={"shoulder_lift": 791})
    calibrator._load_default_calibration = Mock(
        return_value={"shoulder_lift": {"range_min": 295, "range_max": 4037}}
    )
    calibrator._detect_mechanical_limits = Mock(
        return_value={"min": {"shoulder_lift": 295}, "max": {"shoulder_lift": 4037}}
    )

    result = (
        calibrator.auto_calibrate(True) if full else calibrator.default_calibrate(True)
    )

    assert result["shoulder_lift"] == calibration(910, 176, 3918)
    assert robot._save_calibration.call_count == 1
    assert all(
        call.args[0] == result for call in robot.bus.write_calibration.call_args_list
    )


def test_left_arm_calibration_is_unchanged(tmp_path):
    robot = make_robot(tmp_path, "left")
    calibrator = SourcceyFollowerCalibrator(robot)
    result = calibrator._finalize_calibration(
        calibrator._create_calibration_dict(
            {"shoulder_lift": 791},
            {"shoulder_lift": 295},
            {"shoulder_lift": 4037},
        )
    )
    assert result["shoulder_lift"] == calibration()


def test_explicit_opt_out_leaves_right_shoulder_unchanged(tmp_path):
    robot = make_robot(tmp_path, protect=False)
    calibrator = SourcceyFollowerCalibrator(robot)
    result = calibrator._finalize_calibration({"shoulder_lift": calibration()})
    assert result["shoulder_lift"] == calibration()


def test_existing_manual_calibration_is_finalized_and_saved_automatically(tmp_path):
    robot = make_robot(tmp_path)
    robot.calibration = {"shoulder_lift": calibration()}
    calibrator = SourcceyFollowerCalibrator(robot)

    result = calibrator.manual_calibrate()

    assert result["shoulder_lift"] == calibration(910, 176, 3918)
    robot.bus.disable_torque.assert_called_once_with()
    assert all(call.args[0] == result for call in robot.bus.write_calibration.call_args_list)
    robot._save_calibration.assert_called_once_with()


@pytest.mark.parametrize(("motor_id", "model"), [(7, "sts3250"), (8, "sts3215")])
def test_wrong_right_shoulder_motor_refused_before_hardware(tmp_path, motor_id, model):
    robot = make_robot(tmp_path)
    robot.bus.motors["shoulder_lift"] = SimpleNamespace(id=motor_id, model=model)

    with pytest.raises(ValueError, match="STS3250 motor ID 8"):
        SourcceyFollowerCalibrator(robot)

    robot.bus.write_calibration.assert_not_called()


def test_failed_frame_selection_does_not_save_bad_calibration(tmp_path):
    robot = make_robot(tmp_path)
    calibrator = SourcceyFollowerCalibrator(robot)
    calibrator._initialize_calibration = Mock(return_value={"shoulder_lift": 791})
    calibrator._load_default_calibration = Mock(
        return_value={"shoulder_lift": {"range_min": 0, "range_max": 4095}}
    )
    with pytest.raises(ValueError, match="encoder frame"):
        calibrator.default_calibrate(True)
    robot._save_calibration.assert_not_called()
    robot.bus.write_calibration.assert_not_called()


def test_torque_release_must_succeed_before_referencing(tmp_path):
    robot = make_robot(tmp_path)
    robot.bus.disable_torque.side_effect = RuntimeError("bus failed")
    robot.bus.set_half_turn_homings = Mock()
    calibrator = SourcceyFollowerCalibrator(robot)
    with pytest.raises(RuntimeError):
        calibrator._initialize_calibration(True)
    robot.bus.set_half_turn_homings.assert_not_called()

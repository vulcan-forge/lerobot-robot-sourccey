from __future__ import annotations

import numpy as np
import pytest

import lerobot_robot_sourccey.sdk as sdk_module
from lerobot_robot_sourccey import SourcceySDK


def make_sdk(tmp_path, *, cameras=None) -> SourcceySDK:
    overrides = {"calibration_dir": tmp_path}
    if cameras is not None:
        overrides["cameras"] = cameras
    return SourcceySDK.from_ip(" 192.168.1.50 ", robot_id="example", **overrides)


def test_from_ip_builds_sdk_config(tmp_path) -> None:
    robot = make_sdk(tmp_path, cameras={})

    assert robot.remote_ip == "192.168.1.50"
    assert robot.id == "example"
    assert robot.is_calibrated is True
    assert robot.calibrate() is None
    assert robot.configure() is None


def test_from_ip_rejects_empty_address(tmp_path) -> None:
    with pytest.raises(ValueError, match="remote_ip"):
        SourcceySDK.from_ip(" ", calibration_dir=tmp_path)


def test_set_base_velocity_sends_all_axes(tmp_path, monkeypatch) -> None:
    robot = make_sdk(tmp_path, cameras={})
    actions = []
    monkeypatch.setattr(robot, "send_action", lambda action: actions.append(dict(action)) or action)

    robot.set_base_velocity(x=0.25)

    assert actions == [{"x.vel": 0.25, "y.vel": 0.0, "theta.vel": 0.0}]


@pytest.mark.parametrize("value", [-1.01, 1.01, float("inf"), float("nan")])
def test_set_base_velocity_validates_normalized_range(tmp_path, value) -> None:
    robot = make_sdk(tmp_path, cameras={})

    with pytest.raises(ValueError):
        robot.set_base_velocity(x=value)


def test_drive_for_refreshes_command_and_stops(tmp_path, monkeypatch) -> None:
    robot = make_sdk(tmp_path, cameras={})
    robot._is_connected = True
    actions = []
    now = [0.0]

    monkeypatch.setattr(robot, "send_action", lambda action: actions.append(dict(action)) or action)
    monkeypatch.setattr(sdk_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(sdk_module.time, "sleep", lambda duration: now.__setitem__(0, now[0] + duration))

    robot.drive_for(x=0.2, duration_s=0.12, command_rate_hz=20.0)

    assert len(actions) >= 3
    assert all(action["x.vel"] == pytest.approx(0.2) for action in actions[:-1])
    assert actions[-1] == {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}


def test_drive_for_rejects_unsafe_command_rate(tmp_path) -> None:
    robot = make_sdk(tmp_path, cameras={})

    with pytest.raises(ValueError, match="at least 5 Hz"):
        robot.drive_for(x=0.2, duration_s=1.0, command_rate_hz=2.0)


def test_drive_for_stops_when_streaming_raises(tmp_path, monkeypatch) -> None:
    robot = make_sdk(tmp_path, cameras={})
    robot._is_connected = True
    actions = []

    def record_or_fail(action):
        actions.append(dict(action))
        if action["x.vel"] != 0.0:
            raise RuntimeError("stream failed")
        return action

    monkeypatch.setattr(robot, "send_action", record_or_fail)

    with pytest.raises(RuntimeError, match="stream failed"):
        robot.drive_for(x=0.2, duration_s=1.0)

    assert actions[-1] == {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}


@pytest.mark.parametrize("position", [-100.0, 0.0, 100.0])
def test_set_lift_position_accepts_supported_range(tmp_path, monkeypatch, position) -> None:
    robot = make_sdk(tmp_path, cameras={})
    actions = []
    monkeypatch.setattr(robot, "send_action", lambda action: actions.append(dict(action)) or action)

    robot.set_lift_position(position)

    assert actions == [{"z.pos": position}]


def test_get_camera_reuses_observation_and_copies_frame(tmp_path) -> None:
    robot = make_sdk(tmp_path)
    frame = np.zeros((4, 5, 3), dtype=np.uint8)

    captured = robot.get_camera("front_left", observation={"front_left": frame})

    assert np.array_equal(captured, frame)
    assert captured is not frame
    assert "front_left" in robot.available_cameras


def test_get_camera_rejects_unknown_name(tmp_path) -> None:
    robot = make_sdk(tmp_path)

    with pytest.raises(KeyError, match="Unknown Sourccey camera"):
        robot.get_camera("rear", observation={})

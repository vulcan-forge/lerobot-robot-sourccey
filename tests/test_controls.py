import importlib
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lerobot_robot_sourccey import SourcceyClient, SourcceyClientConfig
from lerobot_robot_sourccey.cameras import SourcceyOpenCVCamera
from lerobot_robot_sourccey.controls import make_control_processors
from lerobot_robot_sourccey.teleoperators.keyboard import (
    SourcceyKeyboard,
    SourcceyKeyboardConfig,
)
from lerobot_robot_sourccey.teleoperators.sourccey_teleoperator import (
    SourcceyTeleoperator,
    SourcceyTeleoperatorConfig,
)

from lerobot.cameras.utils import make_cameras_from_configs


def keyboard(tmp_path, **kwargs):
    path = tmp_path / "keys.json"
    result = SourcceyKeyboard(SourcceyKeyboardConfig(input_state_path=str(path), **kwargs))
    result.connect()
    return result, path


def write_keys(path, keys):
    path.write_text(json.dumps(keys), encoding="utf-8")


def test_desktop_bridge_edges_releases_and_reconnect(tmp_path):
    keys, path = keyboard(tmp_path)
    write_keys(path, ["w", "r"])
    assert keys.get_action() == {"w": None, "r": None}
    assert keys.pop_key_down_edges() == ["r", "w"]
    assert keys.pop_key_down_edges() == []
    assert keys.get_action() == {"w": None, "r": None}
    write_keys(path, ["w"])
    assert keys.get_action() == {"w": None}
    write_keys(path, ["w", "r"])
    assert keys.pop_key_down_edges() == ["r"]
    keys.disconnect()
    assert not keys.is_connected
    assert keys.get_action() == {}
    keys.connect()
    assert keys.pop_key_down_edges() == ["r", "w"]


@pytest.mark.parametrize("contents", ["", "not json", "null", '"wasd"', "{}", "[1]", '[["w"]]'])
def test_bad_desktop_state_releases_keys(tmp_path, contents):
    keys, path = keyboard(tmp_path)
    write_keys(path, ["w"])
    assert "w" in keys.get_action()
    path.write_text(contents, encoding="utf-8")
    assert keys.get_action() == {}
    path.unlink()
    assert keys.get_action() == {}


def test_desktop_timeout_is_opt_in(tmp_path):
    keys, path = keyboard(tmp_path, input_state_timeout_s=0.1)
    write_keys(path, ["w"])
    os.utime(path, (1, 1))
    assert keys.get_action() == {}
    keys.config.input_state_timeout_s = None
    assert keys.get_action() == {"w": None}


def test_native_events_normalize_special_keys_without_disconnecting(tmp_path):
    keys, path = keyboard(tmp_path)
    keys.config.input_state_path = None
    keys.listener = Mock(is_alive=Mock(return_value=True))
    keys._enqueue(SimpleNamespace(name="esc"), True)
    keys._enqueue(SimpleNamespace(name="esc"), False)
    keys._enqueue(SimpleNamespace(char="r"), True)
    keys._enqueue(SimpleNamespace(char="r"), True)
    assert keys.pop_key_down_edges() == ["escape", "r"]
    assert keys.is_connected
    assert keys.get_action() == {"r": None}


class FakeArm:
    def __init__(self, fail=False, partial=False):
        self.fail, self.partial = fail, partial
        self.bus = SimpleNamespace(is_connected=False, motors={"joint": object()})
        self.is_connected = False
        self.disconnect_count = 0

    def connect(self, calibrate=True):
        self.bus.is_connected = self.partial
        if self.fail:
            raise ConnectionError("missing serial port")
        self.bus.is_connected = self.is_connected = True

    def disconnect(self):
        self.disconnect_count += 1
        self.bus.is_connected = self.is_connected = False

    def get_action(self):
        return {"joint.pos": 12.0 if self.is_connected else 0.0}


def teleop(tmp_path, **kwargs):
    result = SourcceyTeleoperator(
        SourcceyTeleoperatorConfig(
            left_arm_port="left",
            right_arm_port="right",
            calibration_dir=tmp_path,
            input_state_path=str(tmp_path / "keys.json"),
            **kwargs,
        )
    )
    return result


@pytest.mark.parametrize("left_fail,right_fail", [(False, False), (True, False), (False, True), (True, True)])
def test_partial_leaders_keep_keyboard_and_cleanup(tmp_path, left_fail, right_fail):
    control = teleop(tmp_path)
    control.leader.left_arm = FakeArm(left_fail, partial=left_fail)
    control.leader.right_arm = FakeArm(right_fail, partial=right_fail)
    control.connect()
    assert control.is_connected
    write_keys(tmp_path / "keys.json", ["w"])
    action = control.get_action()
    assert action["x.vel"] > 0
    assert action["left_joint.pos"] == (0 if left_fail else 12)
    assert action["right_joint.pos"] == (0 if right_fail else 12)
    control.disconnect()
    assert not control.is_connected
    assert control.leader.left_arm.disconnect_count == 1
    assert control.leader.right_arm.disconnect_count == 1


def test_strict_leader_failure_closes_already_connected_arm(tmp_path):
    control = teleop(tmp_path, allow_partial_connection=False)
    control.leader.left_arm = FakeArm()
    control.leader.right_arm = FakeArm(True, partial=True)
    with pytest.raises(ConnectionError):
        control.connect()
    assert not control.is_connected
    assert control.leader.left_arm.disconnect_count == 1
    assert control.leader.right_arm.disconnect_count == 1


@pytest.mark.parametrize("strict", [False, True])
def test_keyboard_failure_can_continue_or_fail_strictly(tmp_path, strict):
    control = teleop(tmp_path, allow_keyboard_connection_failure=not strict)
    control.leader.left_arm = FakeArm()
    control.leader.right_arm = FakeArm()
    control.keyboard.connect = Mock(side_effect=RuntimeError("no desktop"))
    if strict:
        with pytest.raises(RuntimeError, match="no desktop"):
            control.connect()
        assert not control.is_connected
        assert not control.leader.left_arm.bus.is_connected
    else:
        control.connect()
        assert control.is_connected
        assert control.get_action()["x.vel"] == 0
        control.disconnect()


@pytest.mark.parametrize(
    "key,expected",
    [
        ("arrowright", {"exit_early": True}),
        ("arrowleft", {"exit_early": True, "rerecord_episode": True}),
        ("escape", {"exit_early": True, "stop_recording": True}),
    ],
)
def test_recording_edges_and_observation_aware_lift(tmp_path, key, expected):
    control = teleop(tmp_path)
    control.leader.left_arm = FakeArm(True)
    control.leader.right_arm = FakeArm(True)
    control.connect()
    client = SourcceyClient(SourcceyClientConfig(remote_ip="127.0.0.1", cameras={}, calibration_dir=tmp_path))
    events = {"exit_early": False, "rerecord_episode": False, "stop_recording": False}
    process, _, _ = make_control_processors(control, client, events)
    write_keys(tmp_path / "keys.json", [key, "w", "r", "n"])
    action = process((control.get_action(), {"z.pos": 42.0}))
    assert action["z.pos"] == 42
    assert action["x.vel"] == 1.0
    assert action["untorque_left"] is True
    assert events == {name: expected.get(name, False) for name in events}
    events.update(dict.fromkeys(events, False))
    held = process((control.get_action(), {"z.pos": 10.0}))
    assert not any(events.values())
    assert held["untorque_left"] is True
    assert held["z.pos"] == 42
    control.disconnect()


def test_camera_uses_standard_factory_and_decode():
    import draccus

    from lerobot.cameras import CameraConfig

    config = draccus.decode(CameraConfig, {"type": "sourccey_opencv", "index_or_path": 0})
    camera = make_cameras_from_configs({"wrist": config})["wrist"]
    assert isinstance(camera, SourcceyOpenCVCamera)
    assert camera.config.auto_reconnect


def test_upstream_runners_have_no_sourccey_fields():
    from dataclasses import fields

    from lerobot.scripts.lerobot_record import RecordConfig
    from lerobot.scripts.lerobot_teleoperate import TeleoperateConfig

    for config in (RecordConfig, TeleoperateConfig):
        assert "teleop_keyboard" not in {field.name for field in fields(config)}


def test_package_commands_import_without_modifying_upstream():
    upstream = importlib.import_module("lerobot.scripts.lerobot_record")
    listener = upstream.init_keyboard_listener
    record = importlib.import_module("lerobot_robot_sourccey.record")
    teleoperate = importlib.import_module("lerobot_robot_sourccey.teleoperate")
    assert record.record_loop is upstream.record_loop
    assert upstream.init_keyboard_listener is listener
    assert callable(teleoperate.teleoperate)

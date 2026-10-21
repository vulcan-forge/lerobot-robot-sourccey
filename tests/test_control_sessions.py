import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lerobot_robot_sourccey import (
    SourcceyClient,
    SourcceyClientConfig,
    SourcceyTeleoperator,
    SourcceyTeleoperatorConfig,
)

from lerobot.configs.dataset import DatasetRecordConfig
from lerobot.scripts.lerobot_record import RecordConfig
from lerobot.scripts.lerobot_teleoperate import TeleoperateConfig

record_module = importlib.import_module("lerobot_robot_sourccey.record")
teleop_module = importlib.import_module("lerobot_robot_sourccey.teleoperate")


def devices(tmp_path, monkeypatch, module):
    path = tmp_path / "keys.json"
    path.write_text(json.dumps(["w", "r", "n", "arrowright"]), encoding="utf-8")
    control = SourcceyTeleoperator(
        SourcceyTeleoperatorConfig(
            left_arm_port="missing-left",
            right_arm_port="missing-right",
            calibration_dir=tmp_path,
            input_state_path=str(path),
        )
    )
    for arm in (control.leader.left_arm, control.leader.right_arm):
        arm.connect = Mock(side_effect=ConnectionError("no leader arm"))
    client = SourcceyClient(SourcceyClientConfig(remote_ip="127.0.0.1", cameras={}, calibration_dir=tmp_path))
    client.connect = lambda: setattr(client, "_is_connected", True)
    client.disconnect = lambda: setattr(client, "_is_connected", False)
    observation = dict.fromkeys(client.observation_features, 0.0)
    observation["z.pos"] = 42.0
    client.get_observation = lambda: observation.copy()
    actions = []

    def send(action):
        assert set(action) == set(client.action_features)
        actions.append(action.copy())
        return action

    client.send_action = send
    monkeypatch.setattr(module, "make_robot_from_config", lambda cfg: client)
    monkeypatch.setattr(module, "make_teleoperator_from_config", lambda cfg: control)
    return control, client, actions


def test_real_record_loop_saves_and_resumes_complete_actions_without_leaders(tmp_path, monkeypatch):
    control, client, actions = devices(tmp_path, monkeypatch, record_module)
    cfg = RecordConfig(
        robot=client.config,
        teleop=control.config,
        play_sounds=False,
        dataset=DatasetRecordConfig(
            repo_id="local/sourccey-test",
            root=tmp_path / "dataset",
            single_task="Control integration",
            video=False,
            push_to_hub=False,
            fps=30,
            num_episodes=1,
            episode_time_s=0.05,
            reset_time_s=0,
        ),
    )
    dataset = record_module.record(cfg)
    assert dataset.num_episodes == 1
    assert actions and all(action["z.pos"] == 42 for action in actions)
    assert actions[0]["x.vel"] == 1.0
    assert actions[0]["untorque_left"] is True
    assert not control.is_connected and not client.is_connected
    cfg.resume = True
    resumed = record_module.record(cfg)
    assert resumed.num_episodes == 2
    assert not control.is_connected and not client.is_connected


def test_real_teleop_loop_works_without_leaders_and_cleans_up(tmp_path, monkeypatch):
    control, client, actions = devices(tmp_path, monkeypatch, teleop_module)
    teleop_module.teleoperate(
        TeleoperateConfig(
            robot=client.config,
            teleop=control.config,
            fps=30,
            teleop_time_s=0.01,
        )
    )
    assert actions[0]["z.pos"] == 42
    assert actions[0]["x.vel"] == 1.0
    assert not client.is_connected
    assert not control.is_connected


@pytest.mark.parametrize("failure", ["robot", "loop", "finalize"])
def test_record_session_attempts_all_cleanup_on_failure(tmp_path, monkeypatch, failure):
    control, client, _ = devices(tmp_path, monkeypatch, record_module)
    dataset = Mock(num_episodes=0)
    monkeypatch.setattr(record_module, "open_dataset", lambda *args: dataset)
    monkeypatch.setattr(record_module, "run_episodes", Mock())
    if failure == "robot":
        client.connect = Mock(side_effect=RuntimeError("robot failure"))
    elif failure == "loop":
        record_module.run_episodes.side_effect = RuntimeError("loop failure")
    else:
        dataset.finalize.side_effect = RuntimeError("finalize failure")
    cfg = RecordConfig(
        robot=client.config,
        teleop=control.config,
        dataset=DatasetRecordConfig(
            repo_id="local/test",
            single_task="test",
            push_to_hub=False,
        ),
    )
    with pytest.raises(RuntimeError, match="failure"):
        record_module.record(cfg)
    dataset.finalize.assert_called_once()
    assert not control.is_connected
    assert not client.is_connected


def test_rerecord_discards_episode_and_resets_controls(monkeypatch):
    events = {"exit_early": False, "rerecord_episode": False, "stop_recording": False}
    dataset = Mock(num_episodes=0)
    dataset.has_pending_frames.return_value = True
    manager = Mock()
    manager.__enter__ = Mock()
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(record_module, "VideoEncodingManager", lambda ds: manager)
    calls = []

    def loop(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            events["rerecord_episode"] = True
        events["exit_early"] = False

    monkeypatch.setattr(record_module, "record_loop", loop)
    cfg = SimpleNamespace(
        dataset=SimpleNamespace(num_episodes=1, fps=30, single_task="test", episode_time_s=1, reset_time_s=1),
        play_sounds=False,
        display_data=False,
        display_mode="rerun",
        display_compressed_images=False,
    )
    record_module.run_episodes(cfg, Mock(), Mock(), dataset, (Mock(), Mock(), Mock()), events)
    assert len(calls) == 3
    assert "dataset" not in calls[1]
    dataset.clear_episode_buffer.assert_called_once()
    dataset.save_episode.assert_called_once()
    assert not any(events.values())

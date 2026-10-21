import json
from pathlib import Path
from unittest.mock import patch

import pytest
from lerobot_robot_sourccey.calibration import CalibrationRecoveryMixin
from lerobot_robot_sourccey.robots.sourccey.config_sourccey import SourcceyClientConfig
from lerobot_robot_sourccey.robots.sourccey.sourccey import Sourccey
from lerobot_robot_sourccey.robots.sourccey.sourccey_client import SourcceyClient
from lerobot_robot_sourccey.robots.sourccey_follower.sourccey_follower import (
    SourcceyFollower,
)
from lerobot_robot_sourccey.teleoperators.sourccey_leader.sourccey_leader import (
    SourcceyLeader,
)


@pytest.mark.parametrize("device", [Sourccey, SourcceyClient, SourcceyFollower, SourcceyLeader])
@pytest.mark.parametrize("content", ["", "{", "[]", '{"joint": {"id": "bad"}}', "null"])
def test_invalid_saved_calibration_is_recoverable_and_preserved(tmp_path, device, content):
    path = tmp_path / "calibration.json"
    path.write_text(content)
    instance = object.__new__(device)
    instance.calibration_fpath = path
    instance.calibration = {"old": object()}
    instance._load_calibration()
    assert instance.calibration == {}
    assert path.read_text() == content


def test_valid_calibration_decodes_and_client_constructor_recovers(tmp_path):
    path = tmp_path / "unit.json"
    path.write_text(
        json.dumps(
            {"joint": {"id": 1, "drive_mode": 0, "homing_offset": 2, "range_min": 0, "range_max": 4095}}
        )
    )
    client = SourcceyClient(
        SourcceyClientConfig(remote_ip="127.0.0.1", id="unit", calibration_dir=tmp_path, cameras={})
    )
    assert client.calibration["joint"].homing_offset == 2
    path.write_text("{")
    client = SourcceyClient(
        SourcceyClientConfig(remote_ip="127.0.0.1", id="unit", calibration_dir=tmp_path, cameras={})
    )
    assert client.calibration == {}


@pytest.mark.parametrize("error", [PermissionError("denied"), OSError("I/O error")])
def test_filesystem_failures_are_not_silenced(tmp_path, error):
    instance = CalibrationRecoveryMixin()
    instance.calibration_fpath = tmp_path / "unit.json"
    with patch.object(Path, "open", side_effect=error), pytest.raises(type(error)):
        instance._load_calibration()

import math
from unittest.mock import Mock

import numpy as np
import pytest
from lerobot_robot_sourccey.policy_observations import ARM_KEYS, MissingArmObservations
from lerobot_robot_sourccey.robots.sourccey.config_sourccey import (
    SourcceyClientConfig,
    SourcceyConfig,
)
from lerobot_robot_sourccey.robots.sourccey.sourccey_client import SourcceyClient


def pose(arm, value):
    return dict.fromkeys(ARM_KEYS[arm], value)


@pytest.mark.parametrize(
    "config",
    [lambda **kw: SourcceyConfig(**kw), lambda **kw: SourcceyClientConfig(remote_ip="127.0.0.1", **kw)],
)
@pytest.mark.parametrize(
    "positions",
    [
        {"unknown": 1.0},
        {"left_gripper.pos": 0.0},
        pose("left", float("nan")),
        pose("right", float("inf")),
        pose("left", True),
    ],
)
def test_invalid_placeholder_contract_fails_before_connect(config, positions):
    with pytest.raises(ValueError):
        config(missing_arm_positions=positions)


@pytest.mark.parametrize("missing", [{"left"}, {"right"}, {"left", "right"}, set()])
def test_substitutes_whole_missing_arms_and_filters_only_their_commands(missing):
    fallback = pose("left", 11.0) | pose("right", 22.0)
    adapter = MissingArmObservations(fallback)
    raw = {key: float("nan") if arm in missing else 33.0 for arm, keys in ARM_KEYS.items() for key in keys}
    raw["z.pos"] = 4.0
    prepared = adapter.observation(raw)
    assert all(math.isfinite(value) for value in prepared.values())
    for arm, keys in ARM_KEYS.items():
        assert all(prepared[key] == (fallback[key] if arm in missing else 33.0) for key in keys)
        assert all(math.isnan(raw[key]) for key in keys) if arm in missing else True
    action = dict.fromkeys(raw, 5.0) | {"x.vel": 0.2, "untorque_left": True, "untorque_right": True}
    sent = adapter.action(action)
    assert sent["x.vel"] == 0.2 and sent["z.pos"] == 5.0
    for arm, keys in ARM_KEYS.items():
        assert bool(keys & sent.keys()) == (arm not in missing)
        assert (f"untorque_{arm}" in sent) == (arm not in missing)


def test_never_substitutes_partial_fault_or_unconfigured_missing_arm():
    adapter = MissingArmObservations(pose("left", 0.0))
    raw = pose("left", 1.0) | pose("right", 2.0)
    raw["left_gripper.pos"] = float("nan")
    with pytest.raises(ValueError, match="partial"):
        adapter.observation(raw)
    with pytest.raises(ValueError, match="Missing right"):
        adapter.observation(pose("left", 1.0) | pose("right", float("nan")))
    with pytest.raises(ValueError, match="Incomplete"):
        adapter.observation({})


def test_client_preserves_raw_packet_and_sends_only_available_arm(tmp_path):
    config = SourcceyClientConfig(
        remote_ip="127.0.0.1", cameras={}, calibration_dir=tmp_path, missing_arm_positions=pose("left", 17.0)
    )
    client = SourcceyClient(config)
    raw = (
        pose("left", float("nan"))
        | pose("right", 10.0)
        | {"z.pos": 2.0, "x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}
    )
    client._is_connected = True
    client._get_data = Mock(return_value=({}, raw, False))
    client.zmq_cmd_socket = Mock()
    try:
        observation = client.get_observation()
        assert observation["left_gripper.pos"] == 17.0
        assert np.isfinite(np.array(list(observation.values()))).all()
        assert math.isnan(raw["left_gripper.pos"])
        client.send_action(pose("left", 55.0) | pose("right", 66.0) | {"x.vel": 0.2})
        packet = client.zmq_cmd_socket.send.call_args.args[0]
        decoded = client.protobuf_converter.protobuf_to_action(
            client.protobuf_converter.action_to_protobuf({}).FromString(packet)
        )
        assert not any(key.startswith("left_") for key in decoded)
        assert decoded["right_gripper.pos"] == 66.0
        assert decoded["x.vel"] == pytest.approx(0.2)
        client._get_data = Mock(return_value=({}, pose("left", 9.0) | pose("right", 10.0), False))
        client.get_observation()
        assert not client._policy_observations.missing_arms
    finally:
        client._is_connected = False

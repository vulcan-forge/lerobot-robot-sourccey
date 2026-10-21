"""Retry budgets belong to Sourccey devices, while transport stays upstream."""

from unittest.mock import patch

import draccus
import pytest
from lerobot_robot_sourccey import (
    BiSourcceyLeader,
    BiSourcceyLeaderConfig,
    Sourccey,
    SourcceyConfig,
    SourcceyFollower,
    SourcceyFollowerConfig,
    SourcceyLeader,
    SourcceyLeaderConfig,
    SourcceyTeleoperator,
    SourcceyTeleoperatorConfig,
)
from lerobot_robot_sourccey.motors.retry import MotorRetryPolicy, SourcceyMotorsBus

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

OPERATIONS = [
    ("read", ("Present_Position", "joint"), 123, "read"),
    ("write", ("Goal_Position", "joint", 456), None, "write"),
    ("sync_read", ("Present_Position", ["joint"]), {"joint": 123}, "read"),
    ("sync_write", ("Goal_Position", {"joint": 456}), None, "write"),
]


def make_bus(policy=None):
    return SourcceyMotorsBus(
        port="unused",
        motors={"joint": Motor(1, "sts3215", MotorNormMode.RANGE_M100_100)},
        retry_policy=policy,
    )


@pytest.mark.parametrize("method,args,result,kind", OPERATIONS)
@pytest.mark.parametrize("policy", [None, MotorRetryPolicy(read=2, write=3)])
@pytest.mark.parametrize("override", [None, 0, 4])
@pytest.mark.parametrize("normalize", [False, True])
def test_budgets_and_explicit_overrides_are_delegated_once(
    method, args, result, kind, policy, override, normalize
):
    bus = make_bus(policy)
    expected = override if override is not None else getattr(policy or MotorRetryPolicy(), kind)
    kwargs = {"normalize": normalize}
    if override is not None:
        kwargs["num_retry"] = override

    with patch.object(FeetechMotorsBus, method, autospec=True, return_value=result) as upstream:
        assert getattr(bus, method)(*args, **kwargs) == result
        upstream.assert_called_once_with(bus, *args, normalize=normalize, num_retry=expected)


def test_sync_read_keeps_the_upstream_all_motors_default():
    bus = make_bus(MotorRetryPolicy(read=2, write=3))
    with patch.object(FeetechMotorsBus, "sync_read", autospec=True, return_value={"joint": 123}) as upstream:
        assert bus.sync_read("Present_Position") == {"joint": 123}
        upstream.assert_called_once_with(bus, "Present_Position", None, normalize=True, num_retry=2)


@pytest.mark.parametrize("method,args,result,kind", OPERATIONS)
@pytest.mark.parametrize("error", [ConnectionError("transport exhausted"), RuntimeError("motor refused")])
def test_upstream_failures_propagate_without_an_outer_retry_loop(method, args, result, kind, error):
    bus = make_bus()
    with patch.object(FeetechMotorsBus, method, autospec=True, side_effect=error) as upstream:
        with pytest.raises(type(error), match=str(error)):
            getattr(bus, method)(*args)
        assert upstream.call_count == 1


@pytest.mark.parametrize("kind", ["read", "write"])
@pytest.mark.parametrize("count", [-1, 1.5, True, "5"])
def test_invalid_configured_budgets_are_rejected(kind, count):
    with pytest.raises(ValueError, match="non-negative integer"):
        MotorRetryPolicy(**{kind: count})


@pytest.mark.parametrize("method,args,result,kind", OPERATIONS)
@pytest.mark.parametrize("count", [-1, 1.5, True, "5"])
def test_invalid_per_call_budgets_never_reach_transport(method, args, result, kind, count):
    bus = make_bus()
    with patch.object(FeetechMotorsBus, method, autospec=True) as upstream:
        with pytest.raises(ValueError, match="non-negative integer"):
            getattr(bus, method)(*args, num_retry=count)
        upstream.assert_not_called()


@pytest.mark.parametrize("device", ["leader", "follower", "bimanual", "composite", "robot"])
def test_policy_reaches_every_arm_bus_without_connecting_hardware(tmp_path, monkeypatch, device):
    import lerobot_robot_sourccey.robots.sourccey_z_actuator.sourccey_z_actuator as z_module

    monkeypatch.setattr(z_module, "HF_LEROBOT_CALIBRATION", tmp_path)
    policy = MotorRetryPolicy(read=2, write=3)
    shared = {"calibration_dir": tmp_path, "motor_retries": policy}
    if device == "leader":
        instance = SourcceyLeader(SourcceyLeaderConfig(port="unused", orientation="left", **shared))
        buses = [instance.bus]
    elif device == "follower":
        instance = SourcceyFollower(SourcceyFollowerConfig(port="unused", cameras={}, **shared))
        buses = [instance.bus]
    elif device == "bimanual":
        instance = BiSourcceyLeader(
            BiSourcceyLeaderConfig(left_arm_port="left", right_arm_port="right", **shared)
        )
        buses = [instance.left_arm.bus, instance.right_arm.bus]
    elif device == "composite":
        instance = SourcceyTeleoperator(
            SourcceyTeleoperatorConfig(
                left_arm_port="left", right_arm_port="right", enable_keyboard=False, **shared
            )
        )
        buses = [instance.leader.left_arm.bus, instance.leader.right_arm.bus]
    else:
        instance = Sourccey(SourcceyConfig(cameras={}, **shared))
        buses = [instance.left_arm.bus, instance.right_arm.bus]

    for bus in buses:
        assert isinstance(bus, SourcceyMotorsBus)
        assert not bus.is_connected
        assert bus.retry_policy == policy


@pytest.mark.parametrize(
    "config,fields",
    [
        (SourcceyFollowerConfig, {"port": "unused"}),
        (SourcceyLeaderConfig, {"port": "unused", "orientation": "left"}),
        (BiSourcceyLeaderConfig, {"left_arm_port": "left", "right_arm_port": "right"}),
        (SourcceyTeleoperatorConfig, {"left_arm_port": "left", "right_arm_port": "right"}),
        (SourcceyConfig, {}),
    ],
)
def test_nested_policy_can_be_decoded_from_lerobot_config(config, fields):
    value = draccus.decode(config, {**fields, "motor_retries": {"read": 0, "write": 2}})
    assert value.motor_retries == MotorRetryPolicy(read=0, write=2)

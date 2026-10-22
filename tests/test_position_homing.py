"""Package homing works through public bus APIs, with no fork-only bus methods."""

from types import SimpleNamespace

import pytest
from lerobot_robot_sourccey.motors.homing import set_position_homings
from lerobot_robot_sourccey.robots.sourccey_follower.sourccey_follower_calibrator import (
    SourcceyFollowerCalibrator,
)
from lerobot_robot_sourccey.teleoperators.sourccey_leader.sourccey_leader_calibrator import (
    SourcceyLeaderCalibrator,
)


class PublicMotorsBus:
    """Only the public upstream operations needed by the package calibrators."""

    def __init__(self, motors=None, actual=None):
        self.motors = motors if motors is not None else {"joint": SimpleNamespace(id=1, model="sts3215")}
        self.actual = actual if actual is not None else dict.fromkeys(self.motors, 0)
        self.calls = []
        self.offsets = {}

    def reset_calibration(self, motors):
        self.calls.append(("reset", list(motors)))

    def sync_read(self, register, motors, *, normalize):
        self.calls.append(("read", register, list(motors), normalize))
        return {name: self.actual[name] for name in motors}

    def write(self, register, motor, value, *, normalize):
        self.calls.append(("write", register, motor, value, normalize))
        self.offsets[motor] = value

    def set_half_turn_homings(self):
        self.calls.append(("half_turn",))
        return {name: 100 + i for i, name in enumerate(self.motors)}

    def disable_torque(self):
        self.calls.append(("disable_torque",))


@pytest.mark.parametrize("model", ["sts3215", "sts3250"])
@pytest.mark.parametrize(
    "actual,target,expected",
    [
        (1337, 2047, -710),
        (4095, 2047, 2047),
        (0, 4095, 1),
        (4095, 0, -1),
        (2047, 2047, 0),
        (2500, 5425, 1171),
        (0, -1, 1),
        (100, 4096, 100),
        (0, 2048, 2047),
        (0, 2047, -2047),
    ],
)
def test_position_homing_preserves_feetech_wraparound(model, actual, target, expected):
    bus = PublicMotorsBus({"joint": SimpleNamespace(id=1, model=model)}, {"joint": actual})
    assert not hasattr(bus, "set_position_homings")

    assert set_position_homings(bus, {1: target}) == {"joint": expected}
    assert bus.calls == [
        ("reset", ["joint"]),
        ("read", "Present_Position", ["joint"], False),
        ("write", "Homing_Offset", "joint", expected, False),
    ]


@pytest.mark.parametrize("target", [1.5, float("nan"), float("inf"), -float("inf")])
def test_invalid_targets_fail_before_bus_operations(target):
    bus = PublicMotorsBus()
    with pytest.raises(ValueError, match="Invalid encoder target"):
        set_position_homings(bus, {"joint": target})
    assert bus.calls == []


@pytest.mark.parametrize("model", ["scs0009", "xl330-m077", "unknown"])
def test_all_models_are_checked_before_bus_operations(model):
    bus = PublicMotorsBus(
        {"joint": SimpleNamespace(id=1, model="sts3215"), "unsupported": SimpleNamespace(id=2, model=model)}
    )
    with pytest.raises(ValueError, match="supports STS3215/STS3250"):
        set_position_homings(bus, {"joint": 2047, "unsupported": 500})
    assert bus.calls == []


@pytest.mark.parametrize("motor", ["missing", 99, None])
def test_unknown_motor_fails_before_bus_operations(motor):
    bus = PublicMotorsBus()
    with pytest.raises(ValueError):
        set_position_homings(bus, {motor: 2047})
    assert bus.calls == []


def test_name_and_id_cannot_select_the_same_motor_twice():
    bus = PublicMotorsBus()
    with pytest.raises(ValueError, match="specified more than once"):
        set_position_homings(bus, {"joint": 2047, 1: 100})
    assert bus.calls == []


def test_later_invalid_target_does_not_reset_an_earlier_valid_motor():
    bus = PublicMotorsBus(
        {"joint": SimpleNamespace(id=1, model="sts3215"), "second": SimpleNamespace(id=2, model="sts3250")}
    )
    with pytest.raises(ValueError):
        set_position_homings(bus, {"joint": 2047, "second": 0.5})
    assert bus.calls == []


def test_empty_request_does_not_touch_bus():
    bus = PublicMotorsBus()
    assert set_position_homings(bus, {}) == {}
    assert bus.calls == []


JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


@pytest.mark.parametrize(
    "reverse,expected",
    [
        (False, (-1544, 460, -112, 2012, -1996, 1382)),
        (True, (1528, -379, 173, 1924, 2022, -1329)),
    ],
)
def test_leader_uses_package_homing_with_unchanged_targets(reverse, expected):
    bus = PublicMotorsBus({name: SimpleNamespace(id=i + 1, model="sts3215") for i, name in enumerate(JOINTS)})
    calibrator = SourcceyLeaderCalibrator(SimpleNamespace(bus=bus))

    offsets = calibrator._initialize_calibration(reverse)

    assert offsets == dict(zip(JOINTS, expected, strict=True))
    assert bus.calls[:2] == [
        ("reset", list(JOINTS)),
        ("read", "Present_Position", list(JOINTS), False),
    ]
    assert offsets == bus.offsets


@pytest.mark.parametrize("reverse,expected", [(False, 296), (True, -296)])
def test_follower_keeps_half_turn_homing_and_custom_shoulder_target(reverse, expected):
    bus = PublicMotorsBus({name: SimpleNamespace(id=i + 1, model="sts3215") for i, name in enumerate(JOINTS)})
    robot = SimpleNamespace(bus=bus, config=SimpleNamespace(orientation="left"))
    calibrator = SourcceyFollowerCalibrator(robot)

    offsets = calibrator._initialize_calibration(reverse)

    assert bus.calls == [
        ("disable_torque",),
        ("half_turn",),
        ("reset", ["shoulder_lift"]),
        ("read", "Present_Position", ["shoulder_lift"], False),
        ("write", "Homing_Offset", "shoulder_lift", expected, False),
    ]
    assert offsets == {
        name: expected if name == "shoulder_lift" else 100 + i for i, name in enumerate(JOINTS)
    }

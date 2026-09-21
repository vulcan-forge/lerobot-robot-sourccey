from argparse import Namespace

from lerobot_robot_sourccey.teleoperators import calibrate as calibrate_command


class FakeTeleoperator:
    instances: list["FakeTeleoperator"] = []

    def __init__(self, config) -> None:
        self.config = config
        self.calls: list[tuple] = []
        self.instances.append(self)

    def connect(self, calibrate: bool = True) -> None:
        self.calls.append(("connect", calibrate))

    def auto_calibrate(self, **kwargs) -> None:
        self.calls.append(("auto_calibrate", kwargs))

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))


class FakeBiTeleoperator(FakeTeleoperator):
    instances: list[FakeTeleoperator] = []


class FakeSingleTeleoperator(FakeTeleoperator):
    instances: list[FakeTeleoperator] = []


def make_args(**overrides) -> Namespace:
    values = {
        "arm": "both",
        "left_arm_port": "COM5",
        "right_arm_port": "COM6",
        "calibration_dir": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_both_arms_use_bimanual_auto_calibration(monkeypatch) -> None:
    FakeBiTeleoperator.instances.clear()
    monkeypatch.setattr(calibrate_command, "BiSourcceyLeader", FakeBiTeleoperator)

    calibrate_command.run_calibration(make_args())

    teleoperator = FakeBiTeleoperator.instances[-1]
    assert teleoperator.config.left_arm_port == "COM5"
    assert teleoperator.config.right_arm_port == "COM6"
    assert teleoperator.calls == [
        ("connect", False),
        ("auto_calibrate", {}),
        ("disconnect",),
    ]


def test_right_arm_uses_right_port_and_reversed_defaults(monkeypatch) -> None:
    FakeSingleTeleoperator.instances.clear()
    monkeypatch.setattr(calibrate_command, "SourcceyLeader", FakeSingleTeleoperator)

    calibrate_command.run_calibration(make_args(arm="right"))

    teleoperator = FakeSingleTeleoperator.instances[-1]
    assert teleoperator.config.id == "sourccey_right"
    assert teleoperator.config.port == "COM6"
    assert teleoperator.config.orientation == "right"
    assert teleoperator.calls == [
        ("connect", False),
        ("auto_calibrate", {"reverse": True}),
        ("disconnect",),
    ]


def test_parser_uses_stable_linux_port_aliases() -> None:
    args = calibrate_command.build_parser().parse_args([])

    assert args.arm == "both"
    assert args.left_arm_port == "/dev/robotLeftArm"
    assert args.right_arm_port == "/dev/robotRightArm"

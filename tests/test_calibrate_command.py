from argparse import Namespace

import pytest

from lerobot_robot_sourccey.robots.sourccey import calibrate as calibrate_command


class FakeDevice:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def connect(self, calibrate: bool = True) -> None:
        self.calls.append(("connect", calibrate))

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))


class FakeRobot(FakeDevice):
    instances: list["FakeRobot"] = []

    def __init__(self, config) -> None:
        super().__init__()
        self.config = config
        self.left_arm = FakeDevice()
        self.right_arm = FakeDevice()
        self.instances.append(self)

    def auto_calibrate(self, *, full_reset: bool, arm: str | None) -> None:
        self.calls.append(("auto_calibrate", full_reset, arm))


def make_args(**overrides) -> Namespace:
    values = {
        "id": "sourccey",
        "arm": "both",
        "left_arm_port": None,
        "right_arm_port": None,
        "calibration_dir": None,
        "full_reset": False,
        "yes": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_soft_calibration_uses_whole_robot_lifecycle(monkeypatch) -> None:
    FakeRobot.instances.clear()
    monkeypatch.setattr(calibrate_command, "Sourccey", FakeRobot)

    calibrate_command.run_calibration(make_args())

    robot = FakeRobot.instances[-1]
    assert robot.calls == [
        ("connect", False),
        ("auto_calibrate", False, None),
        ("disconnect",),
    ]
    assert robot.config.cameras == {}


def test_arm_only_full_reset_does_not_connect_whole_robot(monkeypatch) -> None:
    FakeRobot.instances.clear()
    monkeypatch.setattr(calibrate_command, "Sourccey", FakeRobot)

    calibrate_command.run_calibration(make_args(arm="left", full_reset=True, yes=True))

    robot = FakeRobot.instances[-1]
    assert robot.left_arm.calls == [("connect", False), ("disconnect",)]
    assert robot.right_arm.calls == []
    assert robot.calls == [("auto_calibrate", True, "left")]


def test_full_reset_requires_explicit_acknowledgement(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        calibrate_command.main(["--full-reset"])

    assert exc_info.value.code == 2
    assert "pass --yes to continue" in capsys.readouterr().err

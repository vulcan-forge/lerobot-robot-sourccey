import pytest

from lerobot_robot_sourccey.robots.sourccey_z_actuator.sourccey_z_calibrator import (
    CalibrationPhaseError,
    SourcceyZCalibrator,
)


class FakeSensor:
    def __init__(self) -> None:
        self.calibration_min = 84
        self.calibration_max = 281
        self.invert = True
        self.set_calls: list[tuple[int, int, bool]] = []

    def set_calibration(self, *, raw_min: int, raw_max: int, invert: bool) -> None:
        self.calibration_min = raw_min
        self.calibration_max = raw_max
        self.invert = invert
        self.set_calls.append((raw_min, raw_max, invert))


class FakeActuator:
    def __init__(self) -> None:
        self.sensor = FakeSensor()
        self.is_connected = True
        self.invert = True
        self.saved = False
        self.stop_calls = 0

    def stop_position_controller(self) -> None:
        pass

    def stop(self) -> None:
        self.stop_calls += 1

    def _save_calibration(self) -> None:
        self.saved = True


class EndpointCalibrator(SourcceyZCalibrator):
    def __init__(self, actuator, endpoints: tuple[int, int]) -> None:
        super().__init__(actuator)
        self.endpoints = iter(endpoints)

    def _seek_repeatable_endpoint(self, *args, **kwargs) -> int:
        return next(self.endpoints)

    def _verify_top(self, *, expected_raw_top: int) -> int:
        return expected_raw_top


def test_full_reset_clears_old_bounds_before_seeking_and_saves_new_range() -> None:
    actuator = FakeActuator()
    calibrator = EndpointCalibrator(actuator, (40, 900))

    result = calibrator.auto_calibrate(full_reset=True)

    assert actuator.sensor.set_calls[0] == (0, 1023, True)
    assert actuator.sensor.set_calls[-1] == (40, 900, False)
    assert result.raw_min == 40
    assert result.raw_max == 900
    assert actuator.saved


def test_full_reset_restores_old_bounds_when_measured_span_is_too_small() -> None:
    actuator = FakeActuator()
    calibrator = EndpointCalibrator(actuator, (100, 120))

    with pytest.raises(CalibrationPhaseError, match="span is too small"):
        calibrator.auto_calibrate(full_reset=True)

    assert actuator.sensor.set_calls == [(0, 1023, True), (84, 281, True)]
    assert not actuator.saved


def test_move_to_endpoint_stops_motor_when_detection_fails(monkeypatch) -> None:
    actuator = FakeActuator()
    calibrator = SourcceyZCalibrator(actuator)
    monkeypatch.setattr(calibrator, "_drive", lambda _cmd: None)
    monkeypatch.setattr(
        calibrator,
        "_wait_until_stable",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("stuck")),
    )

    with pytest.raises(TimeoutError, match="stuck"):
        calibrator._move_to_endpoint(1.0, phase="test")

    assert actuator.stop_calls == 1

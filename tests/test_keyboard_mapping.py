from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

import draccus
import pytest
from lerobot.configs import PipelineFeatureType
from lerobot.processor import (
    RobotProcessorPipeline,
    make_default_teleop_action_processor,
)
from lerobot.processor.converters import (
    robot_action_observation_to_transition,
    transition_to_robot_action,
)
from lerobot.teleoperators.composite import (
    CompositeTeleoperator,
    CompositeTeleoperatorConfig,
)
from lerobot.teleoperators.keyboard import KeyboardTeleop, KeyboardTeleopConfig

import lerobot_robot_sourccey.teleoperators.keyboard_mapping as mapping_module
from lerobot_robot_sourccey import SourcceyKeyboardToBaseActionProcessorStep
from lerobot_robot_sourccey.teleoperators.keyboard_mapping import sourccey_key_bindings


def run(step, keys="", observation=None, other=None):
    pipeline = RobotProcessorPipeline(
        steps=[step],
        to_transition=robot_action_observation_to_transition,
        to_output=transition_to_robot_action,
    )
    return pipeline(({**dict.fromkeys(keys), **(other or {})}, observation or {}))


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(mapping_module.time, "monotonic", fake)
    return fake


@pytest.mark.parametrize("layout", ["qwerty", "azerty", "qwertz"])
def test_layouts_have_distinct_keys(layout):
    bindings = SourcceyKeyboardToBaseActionProcessorStep(layout=layout).key_bindings
    assert bindings == sourccey_key_bindings(layout)
    assert len(set(bindings.values())) == len(bindings)


def test_base_speeds_are_normalized():
    step = SourcceyKeyboardToBaseActionProcessorStep()
    action = run(step, "wz", {"z.pos": 0.0})
    assert (action["x.vel"], action["theta.vel"]) == (0.8, 0.8)
    assert run(step, "w+", {"z.pos": 0.0})["x.vel"] == 0.9


def test_lift_starts_at_measured_position_and_moves_while_held(clock):
    step = SourcceyKeyboardToBaseActionProcessorStep()
    assert run(step, "", {"z.pos": 10.0})["z.pos"] == 10.0
    clock.now += 0.04
    assert run(step, "q", {"z.pos": 10.0})["z.pos"] == pytest.approx(11.0)
    clock.now += 1.0  # A stalled loop moves the target by at most lift_max_step.
    assert run(step, "e", {"z.pos": 50.0})["z.pos"] == pytest.approx(9.0)
    clock.now += 0.04
    assert run(step, "", {"z.pos": 50.0})["z.pos"] == pytest.approx(9.0)


def test_lift_is_clamped(clock):
    step = SourcceyKeyboardToBaseActionProcessorStep(lift_max_step=50.0)
    run(step, "", {"z.pos": 99.0})
    clock.now += 1.0
    assert run(step, "q", {"z.pos": 99.0})["z.pos"] == 100.0


@pytest.mark.parametrize("measured", [None, float("nan"), 150.0])
def test_lift_is_omitted_without_a_valid_measurement(measured):
    observation = {} if measured is None else {"z.pos": measured}
    assert "z.pos" not in run(SourcceyKeyboardToBaseActionProcessorStep(), "q", observation)


def test_untorque_toggles_once_per_press_and_resets():
    step = SourcceyKeyboardToBaseActionProcessorStep()
    assert run(step)["untorque_left"] is False
    for _ in range(3):
        assert run(step, "n")["untorque_left"] is True
    run(step)
    action = run(step, "nm")
    assert (action["untorque_left"], action["untorque_right"]) == (False, True)
    step.reset()
    assert run(step)["untorque_right"] is False


def test_other_devices_pass_through():
    action = run(SourcceyKeyboardToBaseActionProcessorStep(), "w", {}, {"left_gripper.pos": 3.0})
    assert action["left_gripper.pos"] == 3.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"key_bindings": dict(sourccey_key_bindings(), lift_up="w")},
        {"key_bindings": {key: value for key, value in sourccey_key_bindings().items() if key != "lift_up"}},
    ],
)
def test_invalid_bindings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        SourcceyKeyboardToBaseActionProcessorStep(**kwargs)


def test_features_include_lift_but_not_untorque():
    features = SourcceyKeyboardToBaseActionProcessorStep().transform_features({})
    assert set(features[PipelineFeatureType.ACTION]) == {"x.vel", "y.vel", "theta.vel", "z.pos"}


def test_cli_selects_the_sourccey_mapping_for_a_keyboard_base(tmp_path):
    @dataclass
    class Config:
        teleop: CompositeTeleoperatorConfig

    config = draccus.parse(
        Config,
        args=[
            "--teleop.base.type=keyboard",
            "--teleop.mapping.type=sourccey_keyboard",
            "--teleop.mapping.layout=azerty",
        ],
    )
    assert isinstance(config.teleop.mapping, SourcceyKeyboardToBaseActionProcessorStep)
    assert config.teleop.mapping.key_bindings["lift_up"] == "a"

    with (
        patch("lerobot.teleoperators.keyboard.teleop_keyboard.require_package"),
        patch.object(KeyboardTeleop, "is_connected", new_callable=PropertyMock, return_value=True),
    ):
        keyboard = KeyboardTeleop(KeyboardTeleopConfig(calibration_dir=tmp_path))
        teleop = CompositeTeleoperator([(keyboard, "")], config.teleop)
        robot = SimpleNamespace(action_features={"left_gripper.pos": float, "z.pos": float, "x.vel": float})
        pipeline = make_default_teleop_action_processor(teleop, robot)
        keyboard.event_queue.put(("a", True))
        action = pipeline((teleop.get_action(), {"left_gripper.pos": 4.0, "z.pos": 20.0}))
    assert action["left_gripper.pos"] == 4.0
    assert action["z.pos"] == 20.0
    assert action["untorque_left"] is False

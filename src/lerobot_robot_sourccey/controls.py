"""Connect Sourccey controls to LeRobot's standard processor and loop APIs."""

from typing import Any

from lerobot.lerobot_types import TransitionKey
from lerobot.processor import RobotProcessorPipeline, make_default_processors
from lerobot.processor.converters import (
    robot_action_observation_to_transition,
    transition_to_robot_action,
)
from lerobot.processor.pipeline import IdentityProcessorStep

from .teleoperators.sourccey_teleoperator import SourcceyTeleoperator


class SourcceyControlStep(IdentityProcessorStep):
    """Apply the client's base/lift mapping with this tick's observation."""

    def __init__(self, teleop: SourcceyTeleoperator) -> None:
        self.teleop = teleop

    def __call__(self, transition: dict) -> dict:
        result = transition.copy()
        result[TransitionKey.ACTION] = self.teleop.process_action(
            transition[TransitionKey.ACTION], transition[TransitionKey.OBSERVATION]
        )
        return result


def make_control_processors(
    teleop: SourcceyTeleoperator, robot: Any, events: dict[str, bool] | None = None
) -> tuple:
    if not isinstance(teleop, SourcceyTeleoperator):
        raise ValueError("Sourccey commands require --teleop.type=sourccey_teleoperator")
    teleop.bind_robot(robot, events)
    _, robot_action, observation = make_default_processors()
    teleop_action = RobotProcessorPipeline(
        steps=[SourcceyControlStep(teleop)],
        to_transition=robot_action_observation_to_transition,
        to_output=transition_to_robot_action,
    )
    return teleop_action, robot_action, observation

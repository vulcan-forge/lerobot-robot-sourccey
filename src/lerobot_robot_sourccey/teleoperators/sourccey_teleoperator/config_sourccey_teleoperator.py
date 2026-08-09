from dataclasses import dataclass, field

from lerobot.teleoperators.config import TeleoperatorConfig


def default_teleop_keys() -> dict[str, str]:
    return {
        "forward": "w",
        "backward": "s",
        "left": "a",
        "right": "d",
        "rotate_left": "z",
        "rotate_right": "x",
        "up": "q",
        "down": "e",
        "speed_up": "r",
        "speed_down": "f",
        "untorque_left": "n",
        "untorque_right": "m",
    }


@TeleoperatorConfig.register_subclass("sourccey_teleoperator")
@dataclass
class SourcceyTeleoperatorConfig(TeleoperatorConfig):
    left_arm_port: str
    right_arm_port: str
    teleop_keys: dict[str, str] = field(default_factory=default_teleop_keys)
    speed_levels: tuple[float, ...] = (0.8, 0.9, 1.0)
    initial_speed_index: int = 1
    z_velocity: float = 1.0
    enable_keyboard: bool = True

    def __post_init__(self) -> None:
        if not self.speed_levels:
            raise ValueError("speed_levels must contain at least one value")
        if not 0 <= self.initial_speed_index < len(self.speed_levels):
            raise ValueError("initial_speed_index must index speed_levels")
        if self.z_velocity <= 0:
            raise ValueError("z_velocity must be positive")

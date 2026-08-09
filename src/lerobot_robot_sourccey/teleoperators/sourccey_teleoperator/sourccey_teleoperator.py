from functools import cached_property
import logging
from typing import Any

from lerobot.teleoperators.keyboard import KeyboardTeleop, KeyboardTeleopConfig
from lerobot.teleoperators.teleoperator import Teleoperator

from ..bi_sourccey_leader.bi_sourccey_leader import BiSourcceyLeader
from ..bi_sourccey_leader.config_bi_sourccey_leader import BiSourcceyLeaderConfig
from .config_sourccey_teleoperator import SourcceyTeleoperatorConfig

logger = logging.getLogger(__name__)


class SourcceyTeleoperator(Teleoperator):
    """Composite bimanual leader and keyboard teleoperator for Sourccey."""

    config_class = SourcceyTeleoperatorConfig
    name = "sourccey_teleoperator"

    def __init__(self, config: SourcceyTeleoperatorConfig):
        super().__init__(config)
        self.config = config
        self.leader = BiSourcceyLeader(
            BiSourcceyLeaderConfig(
                id=f"{config.id}_leader" if config.id else None,
                calibration_dir=config.calibration_dir,
                left_arm_port=config.left_arm_port,
                right_arm_port=config.right_arm_port,
            )
        )
        self.keyboard = (
            KeyboardTeleop(KeyboardTeleopConfig(id=f"{config.id}_keyboard" if config.id else None))
            if config.enable_keyboard
            else None
        )
        self.speed_index = config.initial_speed_index
        self._previous_keys: set[str] = set()
        self._untorque_left = False
        self._untorque_right = False

    @cached_property
    def action_features(self) -> dict[str, type]:
        return {
            **self.leader.action_features,
            "x.vel": float,
            "y.vel": float,
            "theta.vel": float,
            "z.vel": float,
            "untorque_left": bool,
            "untorque_right": bool,
        }

    @cached_property
    def feedback_features(self) -> dict[str, type]:
        return {}

    @property
    def is_connected(self) -> bool:
        keyboard_connected = self.keyboard is None or self.keyboard.is_connected
        return self.leader.is_connected and keyboard_connected

    @property
    def is_calibrated(self) -> bool:
        return self.leader.is_calibrated

    def connect(self, calibrate: bool = True) -> None:
        self.leader.connect(calibrate)
        if self.keyboard is not None:
            try:
                self.keyboard.connect()
            except Exception:
                self.leader.disconnect()
                raise

    def disconnect(self) -> None:
        errors: list[Exception] = []
        if self.keyboard is not None and self.keyboard.is_connected:
            try:
                self.keyboard.disconnect()
            except Exception as exc:
                errors.append(exc)
        if self.leader.is_connected:
            try:
                self.leader.disconnect()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError("Failed to disconnect Sourccey teleoperator cleanly") from errors[0]

    def calibrate(self) -> None:
        self.leader.calibrate()

    def configure(self) -> None:
        self.leader.configure()

    def setup_motors(self) -> None:
        self.leader.setup_motors()

    def get_action(self) -> dict[str, float | bool]:
        action: dict[str, float | bool] = dict(self.leader.get_action())
        pressed = self._pressed_keys()
        action.update(self._base_action(pressed))
        self._previous_keys = pressed
        return action

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        self.leader.send_feedback(feedback)

    def _pressed_keys(self) -> set[str]:
        if self.keyboard is None:
            return set()
        raw = self.keyboard.get_action()
        return {str(key) for key in raw}

    def _on_rising_edge(self, key: str, pressed: set[str]) -> bool:
        return key in pressed and key not in self._previous_keys

    def _base_action(self, pressed: set[str]) -> dict[str, float | bool]:
        keys = self.config.teleop_keys
        if self._on_rising_edge(keys["speed_up"], pressed):
            self.speed_index = min(self.speed_index + 1, len(self.config.speed_levels) - 1)
            logger.info("Sourccey teleop speed index: %d", self.speed_index)
        if self._on_rising_edge(keys["speed_down"], pressed):
            self.speed_index = max(self.speed_index - 1, 0)
            logger.info("Sourccey teleop speed index: %d", self.speed_index)
        if self._on_rising_edge(keys["untorque_left"], pressed):
            self._untorque_left = not self._untorque_left
        if self._on_rising_edge(keys["untorque_right"], pressed):
            self._untorque_right = not self._untorque_right

        speed = float(self.config.speed_levels[self.speed_index])
        x_vel = speed * (float(keys["forward"] in pressed) - float(keys["backward"] in pressed))
        y_vel = speed * (float(keys["left"] in pressed) - float(keys["right"] in pressed))
        theta_vel = speed * (
            float(keys["rotate_left"] in pressed) - float(keys["rotate_right"] in pressed)
        )
        z_vel = self.config.z_velocity * (
            float(keys["up"] in pressed) - float(keys["down"] in pressed)
        )
        return {
            "x.vel": x_vel,
            "y.vel": y_vel,
            "theta.vel": theta_vel,
            "z.vel": z_vel,
            "untorque_left": self._untorque_left,
            "untorque_right": self._untorque_right,
        }


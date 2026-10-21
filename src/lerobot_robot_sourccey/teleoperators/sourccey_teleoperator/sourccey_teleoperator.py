from functools import cached_property
import logging
import time
from typing import Any

from ..keyboard import SourcceyKeyboard, SourcceyKeyboardConfig
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
                motor_retries=config.motor_retries,
                allow_partial_connection=config.allow_partial_connection,
            )
        )
        self.keyboard = (
            SourcceyKeyboard(SourcceyKeyboardConfig(
                id=f"{config.id}_keyboard" if config.id else None,
                input_state_path=config.input_state_path,
                input_state_timeout_s=config.input_state_timeout_s,
            ))
            if config.enable_keyboard
            else None
        )
        self._session_connected = False
        self._robot: Any = None
        self._events: dict[str, bool] | None = None
        self._pressed: set[str] = set()
        self.speed_index = config.initial_speed_index
        self._previous_keys: set[str] = set()
        self._untorque_left = False
        self._untorque_right = False
        self._z_position = float(config.initial_z_position)
        self._last_z_command_t = time.monotonic()

    @cached_property
    def action_features(self) -> dict[str, type]:
        return {
            **self.leader.action_features,
            "x.vel": float,
            "y.vel": float,
            "theta.vel": float,
            "z.pos": float,
            "untorque_left": bool,
            "untorque_right": bool,
        }

    @cached_property
    def feedback_features(self) -> dict[str, type]:
        return {}

    @property
    def is_connected(self) -> bool:
        keyboard_connected = self.keyboard is None or self.keyboard.is_connected
        return self._session_connected and self.leader.is_connected and (keyboard_connected or self.config.allow_keyboard_connection_failure)

    @property
    def is_calibrated(self) -> bool:
        return self.leader.is_calibrated

    def connect(self, calibrate: bool = True) -> None:
        if self._session_connected:
            raise RuntimeError("Sourccey teleoperator session is already connected")
        try:
            self.leader.connect(calibrate)
            if self.keyboard is not None:
                try:
                    self.keyboard.connect()
                    if not self.keyboard.is_connected:
                        raise ConnectionError("Keyboard input is unavailable")
                except Exception as exc:
                    self.keyboard.disconnect()
                    if not self.config.allow_keyboard_connection_failure:
                        raise
                    logger.warning("Keyboard unavailable (%s); continuing without keyboard input", exc)
            self._session_connected = True
        except BaseException:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        self._session_connected = False
        errors: list[Exception] = []
        if self.keyboard is not None:
            try:
                self.keyboard.disconnect()
            except Exception as exc:
                errors.append(exc)
        if self.leader is not None:
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
        self._pressed = pressed
        edges = self.keyboard.pop_key_down_edges() if self.keyboard is not None and self.keyboard.is_connected else []
        for key in edges:
            if self._events is not None and key in ("arrowright", "arrowleft", "escape"):
                self._events["exit_early"] = True
                if key == "arrowleft":
                    self._events["rerecord_episode"] = True
                elif key == "escape":
                    self._events["stop_recording"] = True
            elif self._robot is not None:
                self._robot.on_key_down(key)
        if self._robot is None:
            action.update(self._base_action(pressed))
        self._previous_keys = pressed
        return action

    def bind_robot(self, robot: Any, events: dict[str, bool] | None = None) -> None:
        """Use the client's observation-aware base/lift mapping in package runners."""
        if not callable(getattr(robot, "_from_keyboard_to_base_action", None)):
            raise ValueError("Sourccey controls require a robot with keyboard base/lift mapping")
        self._robot = robot
        self._events = events

    def process_action(self, action: dict, observation: dict) -> dict:
        if self._robot is None:
            return action
        return {**action, **self._robot._from_keyboard_to_base_action(self._pressed, observation.get("z.pos"))}

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        self.leader.send_feedback(feedback)

    def _pressed_keys(self) -> set[str]:
        if self.keyboard is None or not self.keyboard.is_connected:
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
        now = time.monotonic()
        dt = max(0.0, min(now - self._last_z_command_t, 0.1))
        self._last_z_command_t = now
        z_direction = (
            float(keys["up"] in pressed) - float(keys["down"] in pressed)
        )
        self._z_position = max(
            self.config.z_position_min,
            min(
                self._z_position + z_direction * self.config.z_position_units_per_s * dt,
                self.config.z_position_max,
            ),
        )
        return {
            "x.vel": x_vel,
            "y.vel": y_vel,
            "theta.vel": theta_vel,
            "z.pos": self._z_position,
            "untorque_left": self._untorque_left,
            "untorque_right": self._untorque_right,
        }


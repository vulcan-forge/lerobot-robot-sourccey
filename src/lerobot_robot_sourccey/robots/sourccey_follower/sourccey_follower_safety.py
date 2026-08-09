import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class SourcceyFollowerSafety:
    """Slow startup and large joint moves to avoid abrupt position jumps."""

    STEP_SAFETY_STARTUP_WINDOW_S = 3.0
    STEP_SAFETY_DELTA_THRESHOLDS = {
        "shoulder_pan": 120.0,
        "shoulder_lift": 120.0,
        "elbow_flex": 120.0,
        "wrist_flex": 120.0,
        "wrist_roll": 120.0,
        "gripper": 120.0,
    }
    STEP_SAFETY_MAX_STEPS = {
        "shoulder_pan": 5.0,
        "shoulder_lift": 5.0,
        "elbow_flex": 5.0,
        "wrist_flex": 4.0,
        "wrist_roll": 5.0,
        "gripper": 5.0,
    }

    def __init__(self, robot: Any):
        self.robot = robot
        self._action_stream_start_time: float | None = None
        self._step_safety_log_active = False

    def should_use_step_safety(
        self,
        goal_pos: dict[str, float],
        present_pos: dict[str, float],
    ) -> bool:
        """Detect large action jumps or startup transitions that should use slow stepping."""
        now = time.monotonic()
        if self._action_stream_start_time is None:
            self._action_stream_start_time = now

        startup_active = (now - self._action_stream_start_time) <= self.STEP_SAFETY_STARTUP_WINDOW_S

        large_deltas: dict[str, dict[str, float]] = {}
        for motor_name, target_pos in goal_pos.items():
            if motor_name not in present_pos:
                continue

            threshold = self.STEP_SAFETY_DELTA_THRESHOLDS.get(motor_name, 15.0)
            delta = abs(float(target_pos) - float(present_pos[motor_name]))
            if delta >= threshold:
                large_deltas[motor_name] = {
                    "delta": round(delta, 2),
                    "threshold": threshold,
                }

        should_use = startup_active or bool(large_deltas)
        if should_use and not self._step_safety_log_active:
            reasons: list[str] = []
            if startup_active:
                reasons.append(f"startup<{self.STEP_SAFETY_STARTUP_WINDOW_S}s")
            if large_deltas:
                reasons.append(f"large_delta={large_deltas}")

            logger.warning(
                "Step safety trigger for %s arm: %s",
                self.robot.config.orientation,
                ", ".join(reasons),
            )

        self._step_safety_log_active = should_use
        return should_use

    def apply_step_safety(
        self,
        goal_pos: dict[str, float],
        present_pos: dict[str, float],
    ) -> dict[str, float]:
        """Move toward the target in small per-joint increments instead of jumping directly."""
        slowed_goal_pos: dict[str, float] = {}

        for motor_name, target_pos in goal_pos.items():
            if motor_name not in present_pos:
                slowed_goal_pos[motor_name] = target_pos
                continue

            max_step = self.STEP_SAFETY_MAX_STEPS.get(motor_name, 5.0)
            current_pos = float(present_pos[motor_name])
            delta = float(target_pos) - current_pos

            if delta > max_step:
                slowed_goal_pos[motor_name] = current_pos + max_step
            elif delta < -max_step:
                slowed_goal_pos[motor_name] = current_pos - max_step
            else:
                slowed_goal_pos[motor_name] = float(target_pos)

        return slowed_goal_pos


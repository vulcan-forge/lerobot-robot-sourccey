"""Minimal programmatic Sourccey teleoperation example."""

from __future__ import annotations

import time

from lerobot_robot_sourccey import (
    SourcceyClient,
    SourcceyClientConfig,
    SourcceyTeleoperator,
    SourcceyTeleoperatorConfig,
)

from lerobot.utils.robot_utils import precise_sleep


def control_sourccey(
    remote_ip: str,
    left_arm_port: str,
    right_arm_port: str,
    *,
    fps: int = 60,
    duration_s: float | None = None,
) -> None:
    """Control a remote Sourccey with both leader arms and the keyboard.

    The ``sourccey-host`` process must already be running on ``remote_ip``.
    When ``duration_s`` is ``None``, control continues until Ctrl+C.
    """
    if fps <= 0:
        raise ValueError("fps must be positive")
    if duration_s is not None and duration_s <= 0:
        raise ValueError("duration_s must be positive when provided")

    robot = SourcceyClient(SourcceyClientConfig(remote_ip=remote_ip))
    teleop = SourcceyTeleoperator(
        SourcceyTeleoperatorConfig(
            left_arm_port=left_arm_port,
            right_arm_port=right_arm_port,
        )
    )

    started_at = time.perf_counter()
    try:
        teleop.connect()
        robot.connect()

        while duration_s is None or time.perf_counter() - started_at < duration_s:
            loop_started_at = time.perf_counter()

            # Drain the latest state/camera packet before producing the next action.
            robot.get_observation()
            robot.send_action(teleop.get_action())

            elapsed_s = time.perf_counter() - loop_started_at
            precise_sleep(max(1 / fps - elapsed_s, 0.0))
    except KeyboardInterrupt:
        pass
    finally:
        # Disconnect the robot first so it sends its best-effort base stop command.
        try:
            if robot.is_connected:
                robot.disconnect()
        finally:
            if teleop.is_connected:
                teleop.disconnect()


if __name__ == "__main__":
    control_sourccey(
        remote_ip="192.168.1.50",
        left_arm_port="COM5",
        right_arm_port="COM6",
    )

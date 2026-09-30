"""High-level, customer-facing helpers for controlling Sourccey.

``SourcceySDK`` builds on the LeRobot-compatible ``SourcceyClient`` while
keeping convenience methods, validation, and safety behavior in one obvious
public module.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any

import numpy as np

from .robots.sourccey.config_sourccey import SourcceyClientConfig
from .robots.sourccey.sourccey_client import SourcceyClient


class SourcceySDK(SourcceyClient):
    """Friendly Sourccey API layered on the standard LeRobot robot client."""

    @classmethod
    def from_ip(
        cls,
        remote_ip: str,
        *,
        robot_id: str | None = "sourccey",
        **config_overrides: Any,
    ) -> "SourcceySDK":
        """Create a client for a Sourccey host without manually building config."""
        if not remote_ip or not remote_ip.strip():
            raise ValueError("remote_ip must not be empty")
        if "remote_ip" in config_overrides:
            raise TypeError("remote_ip must be passed as the first argument")

        config_values: dict[str, Any] = {
            "remote_ip": remote_ip.strip(),
            **config_overrides,
        }
        if robot_id is not None:
            config_values["id"] = robot_id
        return cls(SourcceyClientConfig(**config_values))

    @property
    def is_calibrated(self) -> bool:
        """Remote calibration is owned by the robot host, not the SDK client."""
        return True

    def calibrate(self) -> None:
        """No-op: run the packaged calibration command on the robot host."""

    def configure(self) -> None:
        """No-op: client configuration is applied during construction."""

    @property
    def available_cameras(self) -> tuple[str, ...]:
        """Camera names configured for this client."""
        return tuple(self.config.cameras)

    def set_base_velocity(
        self,
        *,
        x: float = 0.0,
        y: float = 0.0,
        theta: float = 0.0,
    ) -> dict[str, Any]:
        """Set all normalized base axes, each in the inclusive range [-1, 1].

        This is a streamed command: the host watchdog stops the base if commands
        are not refreshed. Use :meth:`drive_for` for a self-refreshing timed move.
        """
        action = {
            "x.vel": self._normalized_velocity("x", x),
            "y.vel": self._normalized_velocity("y", y),
            "theta.vel": self._normalized_velocity("theta", theta),
        }
        return self.send_action(action)

    def stop_base(self) -> dict[str, Any]:
        """Explicitly stop all three mobile-base axes."""
        return self.set_base_velocity()

    def drive_for(
        self,
        *,
        x: float = 0.0,
        y: float = 0.0,
        theta: float = 0.0,
        duration_s: float,
        command_rate_hz: float = 20.0,
    ) -> None:
        """Drive for a fixed duration, refreshing the watchdog and always stopping."""
        duration_s = self._positive_finite("duration_s", duration_s)
        command_rate_hz = self._positive_finite("command_rate_hz", command_rate_hz)
        if command_rate_hz < 5.0:
            raise ValueError("command_rate_hz must be at least 5 Hz to refresh the host watchdog")
        # Validate before entering the movement loop so invalid input never causes
        # a command followed by an avoidable exception.
        x = self._normalized_velocity("x", x)
        y = self._normalized_velocity("y", y)
        theta = self._normalized_velocity("theta", theta)

        period_s = 1.0 / command_rate_hz
        deadline = time.monotonic() + duration_s
        try:
            while time.monotonic() < deadline:
                self.set_base_velocity(x=x, y=y, theta=theta)
                remaining_s = deadline - time.monotonic()
                if remaining_s > 0:
                    time.sleep(min(period_s, remaining_s))
        finally:
            if self.is_connected:
                self.stop_base()

    def set_lift_position(self, position: float) -> dict[str, Any]:
        """Set the lift target in Sourccey's normalized range [-100, 100]."""
        position = float(position)
        if not math.isfinite(position):
            raise ValueError("position must be finite")
        if not -100.0 <= position <= 100.0:
            raise ValueError("position must be between -100 and 100")
        return self.send_action({"z.pos": position})

    def get_camera(
        self,
        name: str,
        *,
        observation: Mapping[str, Any] | None = None,
        copy: bool = True,
    ) -> np.ndarray:
        """Return one camera frame, optionally reusing an existing observation."""
        if name not in self.config.cameras:
            available = ", ".join(self.available_cameras) or "none"
            raise KeyError(f"Unknown Sourccey camera {name!r}; available cameras: {available}")

        observation = self.get_observation() if observation is None else observation
        if name not in observation:
            raise RuntimeError(f"Observation did not contain camera {name!r}")
        frame = observation[name]
        if not isinstance(frame, np.ndarray):
            raise TypeError(f"Camera {name!r} did not contain a NumPy image")
        return frame.copy() if copy else frame

    @staticmethod
    def _normalized_velocity(axis: str, value: float) -> float:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{axis} must be finite")
        if not -1.0 <= value <= 1.0:
            raise ValueError(f"{axis} must be between -1 and 1")
        return value

    @staticmethod
    def _positive_finite(name: str, value: float) -> float:
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a positive finite number")
        return value


__all__ = ["SourcceySDK"]

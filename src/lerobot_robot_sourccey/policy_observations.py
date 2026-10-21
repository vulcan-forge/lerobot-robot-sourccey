"""Explicit placeholder poses for policy execution with unavailable follower arms.

Placeholders are in the policy's motor units. They are never measured positions.
Only a complete unavailable arm may be substituted; partial/invalid readings fail.
"""

import logging
import math
from collections.abc import Mapping
from typing import Any

from .motors.models import sourccey_motor_models

logger = logging.getLogger(__name__)
ARM_KEYS = {
    arm: frozenset(f"{arm}_{motor}.pos" for motor in sourccey_motor_models()) for arm in ("left", "right")
}


def validate_missing_arm_positions(positions: Mapping[str, float]) -> None:
    unknown = set(positions) - set().union(*ARM_KEYS.values())
    if unknown:
        raise ValueError(f"Unknown missing-arm position keys: {sorted(unknown)}")
    for arm, keys in ARM_KEYS.items():
        provided = keys & positions.keys()
        if provided and provided != keys:
            raise ValueError(f"Provide all six {arm} arm positions; missing {sorted(keys - provided)}")
    if any(isinstance(value, bool) or not math.isfinite(value) for value in positions.values()):
        raise ValueError("Missing-arm placeholder positions must be finite numbers")


class MissingArmObservations:
    """Track substitutions per session and suppress commands to substituted arms."""

    def __init__(self, positions: Mapping[str, float]) -> None:
        validate_missing_arm_positions(positions)
        self.positions = dict(positions)
        self.missing_arms: set[str] = set()

    def observation(self, observation: dict[str, Any]) -> dict[str, Any]:
        result = dict(observation)
        unavailable = set()
        for arm, keys in ARM_KEYS.items():
            if not keys <= observation.keys():
                if keys & self.positions.keys():
                    raise ValueError(f"Incomplete {arm} arm telemetry; cannot substitute a pose")
                continue
            values = [float(observation[key]) for key in keys]
            if all(math.isnan(value) for value in values):
                unavailable.add(arm)
                if keys <= self.positions.keys():
                    result.update({key: self.positions[key] for key in keys})
                    if arm not in self.missing_arms:
                        logger.warning(
                            "%s arm unavailable: using configured policy placeholder; commands suppressed",
                            arm,
                        )
                elif self.positions:
                    raise ValueError(f"Missing {arm} arm needs a complete missing_arm_positions pose")
            elif not all(math.isfinite(value) for value in values):
                raise ValueError(f"Invalid {arm} arm telemetry; refusing partial pose substitution")
        self.missing_arms = unavailable
        return result

    def action(self, action: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in action.items()
            if not any(key.startswith(f"{arm}_") or key == f"untorque_{arm}" for arm in self.missing_arms)
            and key != "action"
        }

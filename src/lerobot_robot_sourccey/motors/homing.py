# Copyright 2026 Vulcan Robotics, Inc. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0

"""Position homing for the Feetech STS motors used by Sourccey."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lerobot.motors.motors_bus import SerialMotorsBus

# Both supported models have a 12-bit encoder and a sign-magnitude homing
# register. Keep this adapter specific to Sourccey's hardware rather than
# assuming the same offset convention for every LeRobot motor family.
_SUPPORTED_MODELS = frozenset({"sts3215", "sts3250"})
_ENCODER_STEPS = 4096
_MAX_OFFSET = 2047


def set_position_homings(
    bus: "SerialMotorsBus", positions: Mapping[str | int, int | float]
) -> dict[str, int]:
    """Make selected motors' current positions match raw encoder targets.

    Only public upstream bus operations are used. The caller must prepare the
    bus for calibration (including disabling torque) before calling. All names,
    models and targets are validated before any calibration is reset or written.

    Feetech subtracts its homing offset from the measured position. Targets may
    span multiple turns; offsets wrap to the encoder range. The unrepresentable
    -2048 offset is clamped to +2047, matching the existing Vulcan calibration.
    The offset calculation and calibration reset match the former fork-specific
    bus method; calibration profiles remain owned by the calling calibrators.

    Args:
        bus: Connected upstream bus containing Sourccey's STS3215/STS3250 motors.
        positions: Raw integer encoder targets, keyed by motor name or ID.

    Returns:
        The raw signed homing offsets written, keyed by motor name.

    Raises:
        ValueError: An unknown motor, unsupported model, duplicate selection or
            non-integer target was requested. No bus writes occur in that case.
    """
    if not positions:
        return {}

    targets: dict[str, int] = {}
    for motor, target in positions.items():
        if isinstance(motor, str):
            name = motor
        elif isinstance(motor, int):
            name = next((name for name, spec in bus.motors.items() if spec.id == motor), "")
        else:
            raise ValueError(f"Motor must be a name or ID, got {motor!r}.")

        if name not in bus.motors:
            raise ValueError(f"Unknown motor {motor!r}.")
        model = bus.motors[name].model
        if model not in _SUPPORTED_MODELS:
            raise ValueError(f"Position homing supports STS3215/STS3250 motors, got {model!r} for {name!r}.")
        if not float(target).is_integer():
            raise ValueError(f"Invalid encoder target {target!r} for motor {name!r}.")
        if name in targets:
            raise ValueError(f"Motor {name!r} was specified more than once.")
        targets[name] = int(target)

    bus.reset_calibration(list(targets))
    actual = bus.sync_read("Present_Position", list(targets), normalize=False)
    offsets: dict[str, int] = {}
    for name, target in targets.items():
        offset = (int(actual[name]) - target) % _ENCODER_STEPS
        if offset > _MAX_OFFSET:
            offset -= _ENCODER_STEPS
        if offset == -(_MAX_OFFSET + 1):
            offset = _MAX_OFFSET
        offsets[name] = offset

    for name, offset in offsets.items():
        bus.write("Homing_Offset", name, offset, normalize=False)
    return offsets

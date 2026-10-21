# Copyright 2026 Vulcan Robotics, Inc. All rights reserved.
# Licensed under the Apache License, Version 2.0.

"""Sourccey's motor retry policy, delegated to upstream LeRobot transport."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lerobot.motors.feetech import FeetechMotorsBus

if TYPE_CHECKING:
    from lerobot.motors.motors_bus import Motor, MotorCalibration, NameOrID, Value


def _validate_retries(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Motor retries must be a non-negative integer, got {value!r}.")


@dataclass(frozen=True)
class MotorRetryPolicy:
    """Additional transport attempts for Sourccey arm reads and writes."""

    read: int = 5
    write: int = 5

    def __post_init__(self) -> None:
        _validate_retries(self.read)
        _validate_retries(self.write)


class SourcceyMotorsBus(FeetechMotorsBus):
    """Apply a package-owned default budget without adding another retry loop.

    The upstream bus handles transport retries and propagates failures normally.
    Explicit per-call budgets, including zero, override the policy. Other motor
    operations retain their upstream behavior and explicit retry choices.
    """

    def __init__(
        self,
        port: str,
        motors: dict[str, Motor],
        calibration: dict[str, MotorCalibration] | None = None,
        *,
        retry_policy: MotorRetryPolicy | None = None,
    ) -> None:
        self.retry_policy = retry_policy if retry_policy is not None else MotorRetryPolicy()
        super().__init__(port=port, motors=motors, calibration=calibration)

    def _retry_budget(self, requested: int | None, default: int) -> int:
        if requested is None:
            return default
        _validate_retries(requested)
        return requested

    def read(
        self, data_name: str, motor: str, *, normalize: bool = True, num_retry: int | None = None
    ) -> Value:
        """Read with the configured read budget unless explicitly overridden."""
        return super().read(
            data_name,
            motor,
            normalize=normalize,
            num_retry=self._retry_budget(num_retry, self.retry_policy.read),
        )

    def write(
        self,
        data_name: str,
        motor: str,
        value: Value,
        *,
        normalize: bool = True,
        num_retry: int | None = None,
    ) -> None:
        """Write with the configured write budget unless explicitly overridden."""
        super().write(
            data_name,
            motor,
            value,
            normalize=normalize,
            num_retry=self._retry_budget(num_retry, self.retry_policy.write),
        )

    def sync_read(
        self,
        data_name: str,
        motors: NameOrID | Sequence[NameOrID] | None = None,
        *,
        normalize: bool = True,
        num_retry: int | None = None,
    ) -> dict[str, Value]:
        """Read a group with the configured read budget."""
        return super().sync_read(
            data_name,
            motors,
            normalize=normalize,
            num_retry=self._retry_budget(num_retry, self.retry_policy.read),
        )

    def sync_write(
        self,
        data_name: str,
        values: Value | dict[str, Value],
        *,
        normalize: bool = True,
        num_retry: int | None = None,
    ) -> None:
        """Write a group with the configured write budget."""
        super().sync_write(
            data_name,
            values,
            normalize=normalize,
            num_retry=self._retry_budget(num_retry, self.retry_policy.write),
        )

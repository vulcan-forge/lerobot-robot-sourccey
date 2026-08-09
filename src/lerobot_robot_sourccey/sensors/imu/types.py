"""Common IMU data structures."""

from __future__ import annotations

from dataclasses import dataclass


Vector3 = tuple[float, float, float]


@dataclass(frozen=True)
class IMUSample:
    """Single timestamped IMU sample in SI units."""

    timestamp_ns: int
    accel_m_s2: Vector3
    gyro_rad_s: Vector3
    mag_uT: Vector3
    temperature_c: float | None = None
    valid: bool = True
    error: str | None = None

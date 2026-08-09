"""Simple IMU calibration helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .types import Vector3


def _v_add(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_mul(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] * b[0], a[1] * b[1], a[2] * b[2])


@dataclass(frozen=True)
class IMUCalibration:
    """Per-axis offset/scale corrections."""

    accel_bias_m_s2: Vector3 = (0.0, 0.0, 0.0)
    gyro_bias_rad_s: Vector3 = (0.0, 0.0, 0.0)
    # For magnetometer, hard-iron offset + soft-iron scale approximation.
    mag_bias_uT: Vector3 = (0.0, 0.0, 0.0)
    mag_scale: Vector3 = (1.0, 1.0, 1.0)

    def apply_accel(self, value: Vector3) -> Vector3:
        return _v_sub(value, self.accel_bias_m_s2)

    def apply_gyro(self, value: Vector3) -> Vector3:
        return _v_sub(value, self.gyro_bias_rad_s)

    def apply_mag(self, value: Vector3) -> Vector3:
        return _v_mul(_v_sub(value, self.mag_bias_uT), self.mag_scale)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "IMUCalibration":
        p = Path(path)
        payload = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            accel_bias_m_s2=tuple(payload.get("accel_bias_m_s2", [0.0, 0.0, 0.0])),  # type: ignore[arg-type]
            gyro_bias_rad_s=tuple(payload.get("gyro_bias_rad_s", [0.0, 0.0, 0.0])),  # type: ignore[arg-type]
            mag_bias_uT=tuple(payload.get("mag_bias_uT", [0.0, 0.0, 0.0])),  # type: ignore[arg-type]
            mag_scale=tuple(payload.get("mag_scale", [1.0, 1.0, 1.0])),  # type: ignore[arg-type]
        )

    def to_json_file(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "accel_bias_m_s2": list(self.accel_bias_m_s2),
            "gyro_bias_rad_s": list(self.gyro_bias_rad_s),
            "mag_bias_uT": list(self.mag_bias_uT),
            "mag_scale": list(self.mag_scale),
        }
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def compute_static_bias(samples: list[Vector3]) -> Vector3:
    """Return mean vector from a static sample set."""
    if not samples:
        raise ValueError("compute_static_bias requires at least one sample")
    n = float(len(samples))
    acc = (0.0, 0.0, 0.0)
    for sample in samples:
        acc = _v_add(acc, sample)
    return (acc[0] / n, acc[1] / n, acc[2] / n)

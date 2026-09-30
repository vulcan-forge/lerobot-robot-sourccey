"""Public data structures for 2D LiDAR scans."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LidarPoint:
    """One LD19 return.

    Angles are degrees clockwise from the sensor's forward/zero mark. Distances
    are metres and intensity is the sensor's raw 8-bit confidence value.
    """

    angle_deg: float
    distance_m: float
    intensity: int


@dataclass(frozen=True, slots=True)
class LidarScan:
    """One complete clockwise revolution of the LiDAR."""

    timestamp_ns: int
    sensor_timestamp_ms: int
    rotation_hz: float
    points: tuple[LidarPoint, ...]

    @property
    def valid_points(self) -> tuple[LidarPoint, ...]:
        """Returns having a non-zero distance."""
        return tuple(point for point in self.points if point.distance_m > 0.0)


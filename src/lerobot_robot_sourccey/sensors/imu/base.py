"""Base interface for IMU implementations."""

from __future__ import annotations

import abc
from dataclasses import dataclass

from .types import IMUSample


@dataclass
class IMUConfig:
    """Configuration for I2C IMU sensors."""

    bus_num: int = 1
    lsm6dsox_address: int = 0x6A
    lis3mdl_address: int = 0x1C
    sample_rate_hz: float = 52.0
    # Keep range values explicit even if a given backend does not apply them yet.
    accel_range_g: float = 4.0
    gyro_range_dps: float = 250.0
    mag_range_gauss: float = 4.0


class BaseIMU(abc.ABC):
    """Abstract IMU interface."""

    def __init__(self, config: IMUConfig) -> None:
        self.config = config
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abc.abstractmethod
    def connect(self) -> None:
        """Open hardware resources."""

    @abc.abstractmethod
    def read(self) -> IMUSample:
        """Read one IMU sample."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close hardware resources."""

    def __enter__(self) -> "BaseIMU":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()

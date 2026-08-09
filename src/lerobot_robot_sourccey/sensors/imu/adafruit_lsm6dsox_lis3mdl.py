"""Adafruit/Blinka IMU implementation for LSM6DSOX + LIS3MDL."""

from __future__ import annotations

import time
from typing import Any

from .base import BaseIMU, IMUConfig
from .calibration import IMUCalibration
from .types import IMUSample


class AdafruitLSM6DSOXLIS3MDLIMU(BaseIMU):
    """Read 9-DoF data from LSM6DSOX + LIS3MDL on a shared I2C bus."""

    def __init__(self, config: IMUConfig, calibration: IMUCalibration | None = None) -> None:
        super().__init__(config)
        self.calibration = calibration if calibration is not None else IMUCalibration()
        self._i2c: Any = None
        self._imu6: Any = None
        self._mag: Any = None
        self._imu6_variant: str | None = None

    @staticmethod
    def _read_whoami(bus_num: int, address: int) -> int | None:
        try:
            from smbus2 import SMBus
        except Exception:  # noqa: BLE001
            return None

        try:
            with SMBus(bus_num) as bus:
                # WHO_AM_I register
                return int(bus.read_byte_data(address, 0x0F))
        except Exception:  # noqa: BLE001
            return None

    def connect(self) -> None:
        if self._connected:
            return

        try:
            import board
            from adafruit_lis3mdl import LIS3MDL
        except ImportError as exc:
            raise RuntimeError(
                "Missing Adafruit IMU dependencies. Install with: "
                "uv sync --extra sourccey or pip install adafruit-blinka "
                "adafruit-circuitpython-lsm6ds adafruit-circuitpython-lis3mdl"
            ) from exc

        candidates: list[tuple[str, Any]] = []
        # Prefer LSM6DSOX first, then common pin-compatible siblings.
        for module_name, class_name in (
            ("adafruit_lsm6ds.lsm6dsox", "LSM6DSOX"),
            ("adafruit_lsm6ds.ism330dhcx", "ISM330DHCX"),
            ("adafruit_lsm6ds.lsm6dso32", "LSM6DSO32"),
            ("adafruit_lsm6ds.lsm6ds33", "LSM6DS33"),
            ("adafruit_lsm6ds.lsm6ds3trc", "LSM6DS3TRC"),
        ):
            try:
                module = __import__(module_name, fromlist=[class_name])
                candidates.append((class_name, getattr(module, class_name)))
            except Exception:  # noqa: BLE001
                continue

        self._i2c = board.I2C()
        errors: list[str] = []
        for variant_name, imu_cls in candidates:
            try:
                self._imu6 = imu_cls(self._i2c, address=int(self.config.lsm6dsox_address))
                self._imu6_variant = variant_name
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{variant_name}: {exc}")

        if self._imu6 is None:
            whoami = self._read_whoami(self.config.bus_num, int(self.config.lsm6dsox_address))
            whoami_str = "unknown" if whoami is None else f"0x{whoami:02X}"
            raise RuntimeError(
                "Failed to initialize any supported LSM6-family variant at "
                f"0x{int(self.config.lsm6dsox_address):02X}. WHO_AM_I={whoami_str}. "
                f"Tried: {', '.join(errors) if errors else 'no driver classes available'}"
            )

        self._mag = LIS3MDL(self._i2c, address=int(self.config.lis3mdl_address))
        self._connected = True

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._imu6 = None
        self._mag = None
        self._i2c = None
        self._imu6_variant = None
        self._connected = False

    def read(self) -> IMUSample:
        if not self._connected:
            raise RuntimeError("IMU is not connected. Call connect() first.")
        assert self._imu6 is not None
        assert self._mag is not None

        try:
            raw_accel = tuple(float(v) for v in self._imu6.acceleration)
            raw_gyro = tuple(float(v) for v in self._imu6.gyro)
            raw_mag = tuple(float(v) for v in self._mag.magnetic)
            temp = float(self._imu6.temperature)
        except Exception as exc:
            return IMUSample(
                timestamp_ns=time.time_ns(),
                accel_m_s2=(0.0, 0.0, 0.0),
                gyro_rad_s=(0.0, 0.0, 0.0),
                mag_uT=(0.0, 0.0, 0.0),
                temperature_c=None,
                valid=False,
                error=str(exc),
            )

        accel = self.calibration.apply_accel(raw_accel)
        gyro = self.calibration.apply_gyro(raw_gyro)
        mag = self.calibration.apply_mag(raw_mag)

        return IMUSample(
            timestamp_ns=time.time_ns(),
            accel_m_s2=accel,
            gyro_rad_s=gyro,
            mag_uT=mag,
            temperature_c=temp,
            valid=True,
            error=None,
        )

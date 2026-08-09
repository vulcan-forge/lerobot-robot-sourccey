from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
from typing import Protocol


class IMUHostConfig(Protocol):
    imu_print_enabled: bool
    imu_print_interval_s: float
    imu_bus_num: int
    imu_lsm6dsox_address: int
    imu_lis3mdl_address: int


@dataclass(slots=True)
class IMUReporterConfig:
    """Standalone config for an IMU telemetry reporter."""

    enabled: bool = False
    interval_s: float = 10.0
    bus_num: int = 1
    lsm6dsox_address: int = 0x6A
    lis3mdl_address: int = 0x1C


class IMUReporter:
    """Background logger that prints IMU telemetry at a fixed interval."""

    def __init__(self, config: IMUHostConfig):
        self.config = config
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._imu = None

    def start(self) -> None:
        if not self.config.imu_print_enabled:
            return
        if self.config.imu_print_interval_s <= 0:
            logging.warning("IMU reporter disabled: imu_print_interval_s must be > 0")
            return
        try:
            from lerobot.sensors.imu import AdafruitLSM6DSOXLIS3MDLIMU, IMUConfig
        except Exception as exc:  # noqa: BLE001
            logging.warning("IMU reporter unavailable (import failed): %s", exc)
            return

        imu_config = IMUConfig(
            bus_num=self.config.imu_bus_num,
            lsm6dsox_address=self.config.imu_lsm6dsox_address,
            lis3mdl_address=self.config.imu_lis3mdl_address,
        )
        self._imu = AdafruitLSM6DSOXLIS3MDLIMU(config=imu_config)
        try:
            self._imu.connect()
        except Exception as exc:  # noqa: BLE001
            logging.warning("IMU reporter disabled: failed to connect IMU (%s)", exc)
            self._imu = None
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="sourccey_imu_reporter")
        self._thread.start()
        print(f"IMU reporter started (interval={self.config.imu_print_interval_s:.2f}s)")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        if self._imu is not None:
            try:
                self._imu.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._imu = None

    def _run(self) -> None:
        assert self._imu is not None
        interval_s = float(self.config.imu_print_interval_s)
        while not self._stop_event.is_set():
            try:
                sample = self._imu.read()
                if sample.valid:
                    stamp = datetime.now(timezone.utc).isoformat()
                    print(
                        f"[{stamp}] IMU accel={tuple(round(v, 4) for v in sample.accel_m_s2)} "
                        f"gyro={tuple(round(v, 4) for v in sample.gyro_rad_s)} "
                        f"mag={tuple(round(v, 2) for v in sample.mag_uT)} "
                        f"temp_c={None if sample.temperature_c is None else round(sample.temperature_c, 2)}"
                    )
                else:
                    logging.warning("IMU read invalid: %s", sample.error)
            except Exception as exc:  # noqa: BLE001
                logging.warning("IMU reporter read error: %s", exc)

            self._stop_event.wait(interval_s)


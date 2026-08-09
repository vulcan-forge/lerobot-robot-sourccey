"""Background IMU polling loop."""

from __future__ import annotations

import threading
import time

from .base import BaseIMU
from .types import IMUSample


class IMUStream:
    """Poll an IMU in a background thread and cache the latest sample."""

    def __init__(self, imu: BaseIMU, sample_rate_hz: float = 50.0) -> None:
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")
        self.imu = imu
        self.sample_rate_hz = sample_rate_hz
        self._latest: IMUSample | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self.imu.connect()
        self._thread = threading.Thread(target=self._run, daemon=True, name="imu_stream")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self.imu.disconnect()

    def latest(self) -> IMUSample | None:
        with self._lock:
            return self._latest

    def _run(self) -> None:
        period = 1.0 / self.sample_rate_hz
        while not self._stop_event.is_set():
            t0 = time.perf_counter()
            sample = self.imu.read()
            with self._lock:
                self._latest = sample
            dt = time.perf_counter() - t0
            time.sleep(max(0.0, period - dt))

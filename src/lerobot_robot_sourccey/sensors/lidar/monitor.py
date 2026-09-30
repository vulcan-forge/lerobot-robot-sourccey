"""Background LD19 monitoring shared by diagnostics and visualization."""

from __future__ import annotations

import threading
import time
from typing import Any, Self

from .ld19 import DEFAULT_BAUDRATE, DEFAULT_DEVICE, LD19Reader
from .types import LidarScan


class LidarMonitor:
    """Continuously read an LD19 and retain its latest health and scan state."""

    def __init__(self, device: str = DEFAULT_DEVICE, *, baudrate: int = DEFAULT_BAUDRATE) -> None:
        self.device = device
        self.baudrate = baudrate
        self._reader: LD19Reader | None = None
        self._latest: LidarScan | None = None
        self._connected = False
        self._error: str | None = None
        self._scan_count = 0
        self._last_scan_monotonic: float | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="lidar_monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        if self._reader is not None:
            self._reader.disconnect()

    def latest_scan(self) -> LidarScan | None:
        with self._lock:
            return self._latest

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            scan = self._latest
            reader = self._reader
            packet_count = reader.parser.packet_count if reader is not None else 0
            crc_errors = reader.parser.crc_error_count if reader is not None else 0
            discarded = reader.parser.discarded_byte_count if reader is not None else 0
            age = None if self._last_scan_monotonic is None else time.monotonic() - self._last_scan_monotonic
            valid = scan.valid_points if scan is not None else ()
            total_packets = packet_count + crc_errors
            healthy = bool(self._connected and scan is not None and age is not None and age < 1.0)
            return {
                "healthy": healthy,
                "connected": self._connected,
                "device": self.device,
                "baudrate": self.baudrate,
                "error": self._error,
                "scan_count": self._scan_count,
                "packet_count": packet_count,
                "crc_error_count": crc_errors,
                "crc_error_percent": (100.0 * crc_errors / total_packets) if total_packets else 0.0,
                "discarded_byte_count": discarded,
                "data_age_s": age,
                "rotation_hz": scan.rotation_hz if scan is not None else None,
                "point_count": len(scan.points) if scan is not None else 0,
                "valid_point_count": len(valid),
                "minimum_distance_m": min((point.distance_m for point in valid), default=None),
                "maximum_distance_m": max((point.distance_m for point in valid), default=None),
            }

    def scan_payload(self) -> dict[str, Any]:
        with self._lock:
            scan = self._latest
            if scan is None:
                return {"scan": None}
            return {
                "scan": {
                    "timestamp_ns": scan.timestamp_ns,
                    "sensor_timestamp_ms": scan.sensor_timestamp_ms,
                    "rotation_hz": round(scan.rotation_hz, 3),
                    "points": [
                        [round(point.angle_deg, 3), round(point.distance_m, 4), point.intensity]
                        for point in scan.points
                    ],
                }
            }

    def _run(self) -> None:
        while not self._stop.is_set():
            reader = LD19Reader(self.device, baudrate=self.baudrate)
            with self._lock:
                self._reader = reader
            try:
                reader.connect()
                with self._lock:
                    self._connected = True
                    self._error = None
                while not self._stop.is_set():
                    for scan in reader.poll():
                        with self._lock:
                            self._latest = scan
                            self._scan_count += 1
                            self._last_scan_monotonic = time.monotonic()
            except Exception as exc:  # noqa: BLE001 - errors are surfaced in diagnostics
                with self._lock:
                    self._connected = False
                    self._error = str(exc)
            finally:
                reader.disconnect()
                with self._lock:
                    self._connected = False
            self._stop.wait(1.0)

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


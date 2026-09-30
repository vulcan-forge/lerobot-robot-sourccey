"""Dependency-light reader for the LDROBOT LD19 2D LiDAR protocol."""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Any, Self

from .types import LidarPoint, LidarScan

PACKET_HEADER = 0x54
PACKET_VER_LEN = 0x2C
POINTS_PER_PACKET = 12
PACKET_SIZE = 47
DEFAULT_DEVICE = "/dev/lidarFront"
DEFAULT_BAUDRATE = 230_400


def crc8(data: bytes | bytearray | memoryview) -> int:
    """Calculate the CRC-8 used by LDROBOT packets (polynomial 0x4D)."""
    checksum = 0
    for value in data:
        checksum ^= value
        for _ in range(8):
            checksum = ((checksum << 1) ^ 0x4D) & 0xFF if checksum & 0x80 else (checksum << 1) & 0xFF
    return checksum


@dataclass(frozen=True, slots=True)
class LD19Packet:
    speed_deg_s: int
    start_angle_deg: float
    end_angle_deg: float
    sensor_timestamp_ms: int
    points: tuple[LidarPoint, ...]


class LD19Parser:
    """Incrementally recover and validate LD19 packets from arbitrary chunks."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.packet_count = 0
        self.crc_error_count = 0
        self.discarded_byte_count = 0

    def feed(self, data: bytes) -> list[LD19Packet]:
        self._buffer.extend(data)
        packets: list[LD19Packet] = []
        signature = bytes((PACKET_HEADER, PACKET_VER_LEN))

        while True:
            offset = self._buffer.find(signature)
            if offset < 0:
                # Retain a possible header byte split across reads.
                keep = 1 if self._buffer.endswith(bytes((PACKET_HEADER,))) else 0
                discarded = len(self._buffer) - keep
                if discarded > 0:
                    del self._buffer[:discarded]
                    self.discarded_byte_count += discarded
                break
            if offset:
                del self._buffer[:offset]
                self.discarded_byte_count += offset
            if len(self._buffer) < PACKET_SIZE:
                break

            raw = bytes(self._buffer[:PACKET_SIZE])
            if crc8(raw[:-1]) != raw[-1]:
                del self._buffer[0]
                self.crc_error_count += 1
                self.discarded_byte_count += 1
                continue

            del self._buffer[:PACKET_SIZE]
            packet = self._decode(raw)
            self.packet_count += 1
            packets.append(packet)

        return packets

    @staticmethod
    def _decode(raw: bytes) -> LD19Packet:
        speed, start_raw = struct.unpack_from("<HH", raw, 2)
        end_raw, timestamp = struct.unpack_from("<HH", raw, 42)
        start = start_raw / 100.0
        end = end_raw / 100.0
        angle_span = ((end_raw - start_raw) % 36_000) / 100.0
        angle_step = angle_span / (POINTS_PER_PACKET - 1)
        points: list[LidarPoint] = []
        for index in range(POINTS_PER_PACKET):
            distance_mm, intensity = struct.unpack_from("<HB", raw, 6 + index * 3)
            points.append(
                LidarPoint(
                    angle_deg=(start + index * angle_step) % 360.0,
                    distance_m=distance_mm / 1000.0,
                    intensity=intensity,
                )
            )
        return LD19Packet(
            speed_deg_s=speed,
            start_angle_deg=start,
            end_angle_deg=end,
            sensor_timestamp_ms=timestamp,
            points=tuple(points),
        )


class LD19ScanAssembler:
    """Combine validated packets into complete revolutions."""

    def __init__(self, *, minimum_points: int = 100) -> None:
        self.minimum_points = minimum_points
        self._synchronized = False
        self._previous_angle: float | None = None
        self._points: list[LidarPoint] = []
        self._speeds: list[int] = []

    def add(self, packet: LD19Packet) -> LidarScan | None:
        completed: LidarScan | None = None
        for point in packet.points:
            wrapped = self._previous_angle is not None and point.angle_deg < self._previous_angle - 180.0
            if wrapped:
                if self._synchronized and len(self._points) >= self.minimum_points:
                    mean_speed = sum(self._speeds) / len(self._speeds) if self._speeds else packet.speed_deg_s
                    completed = LidarScan(
                        timestamp_ns=time.time_ns(),
                        sensor_timestamp_ms=packet.sensor_timestamp_ms,
                        rotation_hz=mean_speed / 360.0,
                        points=tuple(self._points),
                    )
                self._synchronized = True
                self._points = []
                self._speeds = []
            if self._synchronized:
                self._points.append(point)
            self._previous_angle = point.angle_deg
        if self._synchronized:
            self._speeds.append(packet.speed_deg_s)
        return completed


class LD19Reader:
    """Read complete LD19 scans from a serial device.

    ``pyserial`` is imported only when connecting, so packet parsing can be
    used and tested on machines without robot hardware dependencies.
    """

    def __init__(
        self,
        device: str = DEFAULT_DEVICE,
        *,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout_s: float = 0.1,
    ) -> None:
        self.device = device
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.parser = LD19Parser()
        self.assembler = LD19ScanAssembler()
        self._serial: Any | None = None

    @property
    def is_connected(self) -> bool:
        return bool(self._serial is not None and self._serial.is_open)

    def connect(self) -> None:
        if self.is_connected:
            return
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - depends on installation profile
            raise RuntimeError("pyserial is required; install the Sourccey robot profile") from exc
        self._serial = serial.Serial(self.device, self.baudrate, timeout=self.timeout_s)
        self._serial.reset_input_buffer()

    def disconnect(self) -> None:
        if self._serial is not None:
            self._serial.close()
        self._serial = None

    def poll(self) -> list[LidarScan]:
        """Perform one bounded serial read and return any completed scans."""
        if not self.is_connected:
            raise RuntimeError("LiDAR is not connected")
        waiting = int(self._serial.in_waiting)
        data = self._serial.read(max(1, min(waiting, 4096)))
        scans: list[LidarScan] = []
        for packet in self.parser.feed(data):
            scan = self.assembler.add(packet)
            if scan is not None:
                scans.append(scan)
        return scans

    def read_scan(self, *, timeout_s: float = 2.0) -> LidarScan:
        """Wait for one full revolution or raise ``TimeoutError``."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            scans = self.poll()
            if scans:
                return scans[-1]
        raise TimeoutError(f"No complete LD19 scan received from {self.device} within {timeout_s:g}s")

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()


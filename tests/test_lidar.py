from __future__ import annotations

import struct

import pytest

from lerobot_robot_sourccey.sensors.lidar.ld19 import (
    PACKET_SIZE,
    LD19Parser,
    LD19ScanAssembler,
    crc8,
)


def make_packet(start_deg: float, end_deg: float, *, speed: int = 3600, timestamp: int = 42) -> bytes:
    packet = bytearray((0x54, 0x2C))
    packet.extend(struct.pack("<HH", speed, round(start_deg * 100) % 36_000))
    for index in range(12):
        packet.extend(struct.pack("<HB", 1000 + index, 50 + index))
    packet.extend(struct.pack("<HH", round(end_deg * 100) % 36_000, timestamp))
    packet.append(crc8(packet))
    assert len(packet) == PACKET_SIZE
    return bytes(packet)


def test_crc8_matches_ldrobot_polynomial_vector() -> None:
    assert crc8(bytes((0x54, 0x2C))) == 0xD8


def test_parser_recovers_split_packet_after_noise() -> None:
    raw = make_packet(10.0, 21.0)
    parser = LD19Parser()

    assert parser.feed(b"noise" + raw[:15]) == []
    packets = parser.feed(raw[15:])

    assert len(packets) == 1
    assert packets[0].start_angle_deg == pytest.approx(10.0)
    assert packets[0].end_angle_deg == pytest.approx(21.0)
    assert packets[0].points[0].distance_m == pytest.approx(1.0)
    assert packets[0].points[-1].angle_deg == pytest.approx(21.0)
    assert parser.discarded_byte_count == 5


def test_parser_rejects_bad_crc_and_resynchronizes() -> None:
    bad = bytearray(make_packet(0.0, 11.0))
    bad[10] ^= 0x01
    good = make_packet(12.0, 23.0)
    parser = LD19Parser()

    packets = parser.feed(bytes(bad) + good)

    assert len(packets) == 1
    assert packets[0].start_angle_deg == pytest.approx(12.0)
    assert parser.crc_error_count == 1


def test_assembler_emits_complete_revolution() -> None:
    parser = LD19Parser()
    assembler = LD19ScanAssembler(minimum_points=20)
    scans = []
    # Three passes create a synchronization wrap and then one complete scan.
    for _ in range(3):
        for start in range(0, 360, 12):
            packet = parser.feed(make_packet(float(start), float(start + 11)))[0]
            scan = assembler.add(packet)
            if scan is not None:
                scans.append(scan)

    assert scans
    assert len(scans[0].points) == 360
    assert scans[0].rotation_hz == pytest.approx(10.0)
    assert len(scans[0].valid_points) == 360

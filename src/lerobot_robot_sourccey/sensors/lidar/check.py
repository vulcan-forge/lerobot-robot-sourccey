"""Command-line health check for Sourccey's front LD19 LiDAR."""

from __future__ import annotations

import argparse
import json
import time

from .ld19 import DEFAULT_BAUDRATE, DEFAULT_DEVICE
from .monitor import LidarMonitor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check the Sourccey LD19 2D LiDAR stream")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help=f"Serial device (default: {DEFAULT_DEVICE})")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--duration", type=float, default=3.0, help="Sampling time in seconds (default: 3)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser


def _format_value(value: object, suffix: str = "") -> str:
    if value is None:
        return "--"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def main() -> int:
    args = build_parser().parse_args()
    if args.duration <= 0:
        raise SystemExit("--duration must be greater than zero")
    if args.baudrate <= 0:
        raise SystemExit("--baudrate must be greater than zero")

    with LidarMonitor(args.device, baudrate=args.baudrate) as monitor:
        time.sleep(args.duration)
        result = monitor.snapshot()

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        state = "HEALTHY" if result["healthy"] else "NOT HEALTHY"
        print(f"Sourccey LD19: {state}")
        print(f"  Device:       {result['device']} @ {result['baudrate']} baud")
        print(f"  Connected:    {result['connected']}")
        print(f"  Scans:        {result['scan_count']}")
        print(f"  Rotation:     {_format_value(result['rotation_hz'], ' Hz')}")
        print(f"  Points:       {result['valid_point_count']} valid / {result['point_count']} total")
        print(f"  Range:        {_format_value(result['minimum_distance_m'], ' m')} to "
              f"{_format_value(result['maximum_distance_m'], ' m')}")
        print(f"  Packets:      {result['packet_count']}")
        print(f"  CRC errors:   {result['crc_error_count']} ({result['crc_error_percent']:.2f}%)")
        print(f"  Data age:     {_format_value(result['data_age_s'], ' s')}")
        if result["error"]:
            print(f"  Error:        {result['error']}")
    return 0 if result["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


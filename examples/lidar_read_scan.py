"""Read one complete scan directly from Sourccey's front LD19 LiDAR."""

from __future__ import annotations

import argparse

from lerobot_robot_sourccey.sensors.lidar import DEFAULT_DEVICE, LD19Reader, LidarScan


def read_lidar_scan(device: str = DEFAULT_DEVICE, *, timeout_s: float = 2.0) -> LidarScan:
    """Connect to an LD19 and return one validated 360-degree scan."""
    with LD19Reader(device) as lidar:
        return lidar.read_scan(timeout_s=timeout_s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    scan = read_lidar_scan(args.device, timeout_s=args.timeout)
    valid = scan.valid_points
    print(f"rotation={scan.rotation_hz:.2f} Hz points={len(valid)}/{len(scan.points)}")
    if valid:
        nearest = min(valid, key=lambda point: point.distance_m)
        print(
            f"nearest={nearest.distance_m:.3f} m "
            f"angle={nearest.angle_deg:.1f} deg intensity={nearest.intensity}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


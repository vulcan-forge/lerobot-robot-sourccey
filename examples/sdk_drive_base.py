"""Safely drive Sourccey's base for a fixed duration."""

from __future__ import annotations

import argparse

from lerobot_robot_sourccey import SourcceySDK


def drive_base(
    remote_ip: str,
    *,
    x: float = 0.0,
    y: float = 0.0,
    theta: float = 0.0,
    duration_s: float,
) -> None:
    """Drive with normalized velocities and stop even if execution is interrupted."""
    with SourcceySDK.from_ip(remote_ip) as robot:
        robot.drive_for(x=x, y=y, theta=theta, duration_s=duration_s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True, help="Sourccey host IP address or hostname")
    parser.add_argument("--x", type=float, default=0.0, help="Forward velocity from -1 to 1")
    parser.add_argument("--y", type=float, default=0.0, help="Left velocity from -1 to 1")
    parser.add_argument("--theta", type=float, default=0.0, help="Turn velocity from -1 to 1")
    parser.add_argument("--duration", type=float, required=True, help="Movement duration in seconds")
    args = parser.parse_args()

    print("Ensure the robot has a clear path and the emergency stop is accessible.")
    drive_base(
        args.ip,
        x=args.x,
        y=args.y,
        theta=args.theta,
        duration_s=args.duration,
    )


if __name__ == "__main__":
    main()

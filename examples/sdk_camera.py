"""Capture one Sourccey camera frame through the high-level SDK."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from lerobot_robot_sourccey import SourcceySDK


def capture_camera(remote_ip: str, camera_name: str) -> np.ndarray:
    """Connect, capture one named camera frame, and disconnect safely."""
    with SourcceySDK.from_ip(remote_ip) as robot:
        observation = robot.get_observation()
        return robot.get_camera(camera_name, observation=observation)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True, help="Sourccey host IP address or hostname")
    parser.add_argument("--camera", default="front_left", help="Configured camera name")
    parser.add_argument("--output", type=Path, help="Optional JPEG/PNG output path")
    args = parser.parse_args()

    frame = capture_camera(args.ip, args.camera)
    print(f"Captured {args.camera}: shape={frame.shape} dtype={frame.dtype}")
    if args.output is not None:
        if not cv2.imwrite(str(args.output), frame):
            raise RuntimeError(f"Failed to write camera frame to {args.output}")
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

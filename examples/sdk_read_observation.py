"""Read one Sourccey observation through the high-level SDK."""

from __future__ import annotations

import argparse
from typing import Any

import numpy as np

from lerobot_robot_sourccey import SourcceySDK


def read_observation(remote_ip: str) -> dict[str, Any]:
    """Connect, read one complete observation, and disconnect safely."""
    with SourcceySDK.from_ip(remote_ip) as robot:
        return robot.get_observation()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True, help="Sourccey host IP address or hostname")
    args = parser.parse_args()

    observation = read_observation(args.ip)
    for name, value in observation.items():
        if isinstance(value, np.ndarray):
            print(f"{name}: ndarray shape={value.shape} dtype={value.dtype}")
        else:
            print(f"{name}: {value}")


if __name__ == "__main__":
    main()

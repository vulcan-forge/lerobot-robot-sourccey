"""Command-line entry point for Sourccey leader-arm auto-calibration."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from .bi_sourccey_leader.bi_sourccey_leader import BiSourcceyLeader
from .bi_sourccey_leader.config_bi_sourccey_leader import BiSourcceyLeaderConfig
from .sourccey_leader.config_sourccey_leader import SourcceyLeaderConfig
from .sourccey_leader.sourccey_leader import SourcceyLeader


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Automatically calibrate the Sourccey leader-arm teleoperator using "
            "the packaged left- and right-arm ranges."
        )
    )
    parser.add_argument(
        "--arm",
        choices=("both", "left", "right"),
        default="both",
        help="Calibrate both leader arms or only one arm (default: both).",
    )
    parser.add_argument(
        "--left-arm-port",
        default="/dev/robotLeftArm",
        help="Left leader-arm serial port (default: /dev/robotLeftArm).",
    )
    parser.add_argument(
        "--right-arm-port",
        default="/dev/robotRightArm",
        help="Right leader-arm serial port (default: /dev/robotRightArm).",
    )
    parser.add_argument(
        "--calibration-dir",
        type=Path,
        default=None,
        help="Override the directory used for leader-arm calibration files.",
    )
    return parser


def make_teleoperator(args: argparse.Namespace) -> BiSourcceyLeader | SourcceyLeader:
    if args.arm == "both":
        return BiSourcceyLeader(
            BiSourcceyLeaderConfig(
                id="sourccey_leader",
                calibration_dir=args.calibration_dir,
                left_arm_port=args.left_arm_port,
                right_arm_port=args.right_arm_port,
            )
        )

    port = args.left_arm_port if args.arm == "left" else args.right_arm_port
    return SourcceyLeader(
        SourcceyLeaderConfig(
            id=f"sourccey_{args.arm}",
            calibration_dir=args.calibration_dir,
            port=port,
            orientation=args.arm,
        )
    )


def run_calibration(args: argparse.Namespace) -> None:
    teleoperator = make_teleoperator(args)
    connect_attempted = False
    try:
        connect_attempted = True
        teleoperator.connect(calibrate=False)
        if args.arm == "both":
            teleoperator.auto_calibrate()
        else:
            teleoperator.auto_calibrate(reverse=args.arm == "right")
    finally:
        if connect_attempted:
            try:
                teleoperator.disconnect()
            except Exception:
                logger.exception("Failed to disconnect leader arm(s) cleanly after calibration")


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    run_calibration(args)


if __name__ == "__main__":
    main()

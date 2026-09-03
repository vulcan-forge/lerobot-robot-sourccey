"""Command-line entry point for Sourccey's automatic calibration modes."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from .config_sourccey import SourcceyConfig
from .sourccey import Sourccey


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Automatically calibrate Sourccey. The default soft mode applies the "
            "packaged arm ranges and preserves the current Z limits."
        )
    )
    parser.add_argument("--id", default="sourccey", help="Robot id used for arm calibration files.")
    parser.add_argument(
        "--arm",
        choices=("both", "left", "right"),
        default="both",
        help="Calibrate both arms and Z, or only one arm (default: both).",
    )
    parser.add_argument("--left-arm-port", default=None, help="Override the left arm serial port.")
    parser.add_argument("--right-arm-port", default=None, help="Override the right arm serial port.")
    parser.add_argument(
        "--calibration-dir",
        type=Path,
        default=None,
        help="Override the directory used for arm calibration files.",
    )
    parser.add_argument(
        "--full-reset",
        action="store_true",
        help=(
            "Physically seek mechanical limits and replace calibration ranges. "
            "With --arm=both, this also moves the Z actuator to both endpoints."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Acknowledge the hardware movement required by --full-reset.",
    )
    return parser


def run_calibration(args: argparse.Namespace) -> None:
    config = SourcceyConfig(id=args.id, calibration_dir=args.calibration_dir, cameras={})
    if args.left_arm_port:
        config.left_arm_port = args.left_arm_port
    if args.right_arm_port:
        config.right_arm_port = args.right_arm_port

    robot = Sourccey(config)
    selected_arm = None if args.arm == "both" else args.arm

    # An arm-only run should not initialize the other arm, base, Z actuator, or
    # cameras. A whole-robot run uses the normal lifecycle because it includes Z.
    device = robot if selected_arm is None else getattr(robot, f"{selected_arm}_arm")
    connect_attempted = False
    try:
        connect_attempted = True
        device.connect(calibrate=False)
        robot.auto_calibrate(full_reset=args.full_reset, arm=selected_arm)
    finally:
        if connect_attempted:
            try:
                device.disconnect()
            except Exception:
                logger.exception("Failed to disconnect cleanly after calibration")


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.full_reset and not args.yes:
        parser.error(
            "--full-reset moves the selected arm(s) to their mechanical limits and may move Z; "
            "clear the workspace and pass --yes to continue"
        )

    logging.basicConfig(level=logging.INFO)
    run_calibration(args)


if __name__ == "__main__":
    main()

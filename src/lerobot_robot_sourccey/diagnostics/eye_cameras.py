#!/usr/bin/env python3
"""Live check of Sourccey's two eye cameras plus the bottom (underside) camera.

Runs on your control PC and connects to the robot exactly like the teleop client
does — the host's observation stream on `tcp://<remote-ip>:5556` — so
`sourccey-host` must be running on the Pi. The connection is passive
(observations only, no command socket), so this cannot move the robot.

    # watch the feeds live
    uv run --no-sync sourccey-check-eye-cameras --remote-ip 192.168.1.237

    # unattended 15s pass/fail with saved frames, no viewer
    uv run --no-sync sourccey-check-eye-cameras --remote-ip 192.168.1.237 \
        --view none --seconds 15 --save-dir camera_health

Cameras checked:
  front_left   /dev/cameraFrontLeft
  front_right  /dev/cameraFrontRight
  bottom       the underside camera

NOTE: `bottom` is not in this branch's `sourccey_cameras_config()`, so the host
does not open it unless you have added it. If the host is not publishing it, the
summary says so explicitly rather than pretending the camera is dead — use
`--skip-bottom` to check only the two eyes.

Exit code is 0 only when every expected camera delivered live, non-blank,
non-frozen frames.
"""

from __future__ import annotations

from lerobot_robot_sourccey.robots.sourccey.config_sourccey import (
    sourccey_cameras_config,
)

from .camera_remote import build_parser, run_camera_check

CAMERA_KEYS = ("front_left", "front_right", "bottom")


def main() -> int:
    parser = build_parser("Live view + health check for the two eye cameras and the bottom camera.")
    parser.add_argument(
        "--skip-bottom",
        action="store_true",
        help="Check only the two eye cameras (the host does not publish a bottom camera).",
    )
    parser.add_argument(
        "--bottom-key",
        default="bottom",
        help="Name the host publishes the underside camera under, if it differs.",
    )
    args = parser.parse_args()

    keys = (
        ("front_left", "front_right")
        if args.skip_bottom
        else (
            "front_left",
            "front_right",
            args.bottom_key,
        )
    )
    # Frame rates come from the robot's own camera config, so the "is it slow?"
    # judgement is made against what the host is actually configured to deliver.
    configured = sourccey_cameras_config()
    expected_fps = {key: float(configured[key].fps) for key in keys if key in configured}
    return run_camera_check(keys, expected_fps, "Sourccey eye + bottom cameras", args)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Check the two eye cameras (and the bottom camera) directly - run this ON THE PI.

Opens `/dev/cameraFrontLeft` and `/dev/cameraFrontRight` itself, so it needs no
host and no network. That is the point: over the observation stream, a broken
camera and a camera the host never opened look the same, because the host
substitutes a black frame when a read fails. Here you see the device itself.

`sourccey-host` must be STOPPED - it holds the cameras exclusively, so a
running host shows up as a loud open failure rather than a misleading pass.

    # check both eyes (5s, saves a frame from each)
    uv run --no-sync sourccey-check-eye-cameras-local

    # include the underside camera too
    uv run --no-sync sourccey-check-eye-cameras-local --include-bottom

    # watch them live from your PC while it runs
    uv run --no-sync sourccey-check-eye-cameras-local --view mjpeg --seconds 0

For the same cameras as the ROBOT sees them (host running, from your control PC),
use `sourccey-check-eye-cameras --remote-ip <pi-ip>` instead.

Exit code is 0 only when every camera opened and produced live, non-blank,
non-frozen frames.
"""

from __future__ import annotations

import os

from .camera_devices import (
    CAMERA_DEVICES,
    CameraSpec,
    build_parser,
    run_device_check,
    specs_for,
)

EYE_KEYS = ("front_left", "front_right")
# Set by sourccey-check-bottom-camera --name-it; not in the robot config yet.
DEFAULT_BOTTOM_DEVICE = CAMERA_DEVICES["bottom"]


def main() -> int:
    parser = build_parser("Check the eye cameras directly on the Pi.")
    parser.add_argument(
        "--include-bottom",
        action="store_true",
        help="Also check the underside camera.",
    )
    parser.add_argument(
        "--bottom-device",
        default=DEFAULT_BOTTOM_DEVICE,
        help=f"Device for the underside camera (default: {DEFAULT_BOTTOM_DEVICE}).",
    )
    args = parser.parse_args()

    specs = specs_for(EYE_KEYS, args)
    title = "Sourccey eye cameras (direct)"
    if args.include_bottom:
        if not os.path.exists(args.bottom_device):
            print(f"[check] FAIL  {args.bottom_device} does not exist")
            print("[check]       name it first: sourccey-check-bottom-camera --identify --name-it")
            print("[check]       or pass --bottom-device /dev/videoN")
            return 1
        # The bottom camera needs MJPG at 320x240 to reach 30 FPS on this USB budget.
        specs.append(
            CameraSpec(
                key="bottom",
                path=args.bottom_device,
                width=args.width,
                height=args.height,
                fps=args.fps,
                fourcc=args.fourcc or "MJPG",
            )
        )
        title = "Sourccey eye + bottom cameras (direct)"

    return run_device_check(specs, title, args)


if __name__ == "__main__":
    raise SystemExit(main())

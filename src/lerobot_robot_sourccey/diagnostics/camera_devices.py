"""Shared direct-device camera diagnostics for the robot computer.

These open the V4L2 devices directly, so they answer a question the remote checks
cannot: is the CAMERA broken, or did the host simply not open it? Over the
observation stream both look identical - a missing key or black frames - because
the host substitutes a blank frame when a camera read fails.

Run them ON THE PI with `sourccey-host` STOPPED: it holds the cameras
exclusively, so a running host shows up here as a loud open failure rather than a
misleading pass.

Each camera is read on its own thread, so one stalled device stalls only itself.
Per the stack's hard directives there are no silent fallbacks: a camera that will
not open, returns black frames, or freezes is reported as FAIL with the reason.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from lerobot_robot_sourccey.robots.sourccey.config_sourccey import (
    sourccey_cameras_config,
)

from .preview import MjpegServer, gui_available, lan_ip

# Use the package's canonical camera defaults. Direct checks deliberately
# inspect failed reads without auto-recovery, so hardware faults remain visible.
_camera_defaults = sourccey_cameras_config()
CAMERA_DEVICES = {key: str(config.index_or_path) for key, config in _camera_defaults.items()}
CAMERA_DEVICES["bottom"] = "/dev/cameraFrontBottom"
DEFAULT_WIDTH = _camera_defaults["front_left"].width
DEFAULT_HEIGHT = _camera_defaults["front_left"].height
DEFAULT_FPS = _camera_defaults["front_left"].fps

# A frame whose pixel spread is below this is effectively a blank sensor output:
# lens cap, dead exposure, or a stream that opened but never delivered light.
BLANK_FRAME_STD = 1.5
# Fraction of frames that may be identical to their predecessor before the feed
# is called frozen (a stalled UVC stream keeps handing back its last buffer).
FROZEN_FRAME_RATIO = 0.9
# Consecutive read failures after which a camera worker gives up and reports DEAD.
MAX_CONSECUTIVE_READ_FAILURES = 30


@dataclass
class CameraSpec:
    """One camera to check: where it lives and how to open it."""

    key: str
    path: str
    width: int
    height: int
    fps: int
    fourcc: str | None = None


def specs_for(keys: tuple[str, ...], args: argparse.Namespace) -> list[CameraSpec]:
    """Build capture specs for the named cameras, honouring CLI overrides."""
    overrides = dict(pair.split("=", 1) for pair in args.device or [])
    unknown = set(overrides) - set(CAMERA_DEVICES)
    if unknown:
        raise KeyError(f"unknown camera name(s) in --device: {', '.join(sorted(unknown))}")

    return [
        CameraSpec(
            key=key,
            path=overrides.get(key, CAMERA_DEVICES[key]),
            width=args.width,
            height=args.height,
            fps=args.fps,
            fourcc=args.fourcc or None,
        )
        for key in keys
    ]


@dataclass
class CameraStats:
    """Live health counters for one camera, filled in by its worker thread."""

    opened: bool = False
    open_error: str | None = None
    frames: int = 0
    read_failures: int = 0
    frozen_frames: int = 0
    blank_frames: int = 0
    dead: bool = False
    dead_reason: str | None = None
    negotiated: str = ""
    stamps: deque[float] = field(default_factory=lambda: deque(maxlen=90))

    def fps(self) -> float:
        if len(self.stamps) < 2:
            return 0.0
        span = self.stamps[-1] - self.stamps[0]
        return (len(self.stamps) - 1) / span if span > 0 else 0.0


class CameraWorker(threading.Thread):
    """Reads one camera on its own thread so a stalled device stalls only itself."""

    def __init__(self, spec: CameraSpec) -> None:
        super().__init__(daemon=True, name=f"check_{spec.key}")
        self.spec = spec
        self.stats = CameraStats()
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        # NOT `_stop`: threading.Thread._stop is an internal method that join()
        # calls, and shadowing it breaks teardown of a started thread.
        self._stop_event = threading.Event()
        self._cap: cv2.VideoCapture | None = None
        self._prev_checksum: int | None = None

    def open(self) -> bool:
        """Open the device and apply the robot's capture settings.

        Returns False with `stats.open_error` set rather than raising, so every
        camera's status is reported in one pass instead of aborting on the first
        bad one.
        """
        spec = self.spec
        if spec.path.startswith("/dev/") and not os.path.exists(spec.path):
            self.stats.open_error = f"device path does not exist: {spec.path}"
            return False

        cap = cv2.VideoCapture(spec.path, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            self.stats.open_error = (
                f"cv2 could not open {spec.path} (is sourccey-host or another process holding it?)"
            )
            return False

        if spec.fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*spec.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, spec.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, spec.height)
        cap.set(cv2.CAP_PROP_FPS, spec.fps)
        # Small buffer keeps the preview honest: show the CURRENT view, not a
        # backlog queued while a previous frame was being drawn.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
        actual_fourcc = "".join(chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)).strip()
        self.stats.negotiated = (
            f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
            f"@{cap.get(cv2.CAP_PROP_FPS):.0f} {actual_fourcc or '????'}"
        )
        self._cap = cap
        self.stats.opened = True
        return True

    def run(self) -> None:
        consecutive_failures = 0
        while not self._stop_event.is_set():
            cap = self._cap
            if cap is None:
                return
            ok, frame = cap.read()
            if not ok or frame is None:
                self.stats.read_failures += 1
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    # Fail loud: stop pretending there is a feed here.
                    self.stats.dead = True
                    self.stats.dead_reason = f"{consecutive_failures} consecutive read failures - feed lost"
                    return
                time.sleep(0.02)
                continue

            consecutive_failures = 0
            self.stats.frames += 1
            self.stats.stamps.append(time.monotonic())
            # A frozen stream keeps returning the identical buffer and a dead
            # sensor returns a flat frame; both "read OK" but are not vision.
            checksum = int(frame[::8, ::8].sum())
            if self._prev_checksum is not None and checksum == self._prev_checksum:
                self.stats.frozen_frames += 1
            self._prev_checksum = checksum
            if float(frame.std()) < BLANK_FRAME_STD:
                self.stats.blank_frames += 1
            with self._lock:
                self._frame = frame

    def latest(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def verdict(self) -> tuple[str, str]:
        """Return (PASS|WARN|FAIL, reason) for the end-of-run summary."""
        stats = self.stats
        if not stats.opened:
            return "FAIL", stats.open_error or "did not open"
        if stats.dead:
            return "FAIL", stats.dead_reason or "feed died"
        if stats.frames == 0:
            return "FAIL", "opened but delivered zero frames"
        if stats.blank_frames >= stats.frames:
            return "FAIL", f"all {stats.frames} frames are black/flat - no image data"
        if stats.frames > 10 and stats.frozen_frames > FROZEN_FRAME_RATIO * stats.frames:
            return "FAIL", f"feed is frozen ({stats.frozen_frames}/{stats.frames} identical frames)"

        fps = stats.fps()
        detail = f"{stats.frames} frames at {fps:.1f} fps"
        if stats.blank_frames:
            return "WARN", (
                f"{stats.blank_frames}/{stats.frames} frames were black - the camera is "
                "intermittently failing to read"
            )
        if stats.frozen_frames:
            return "WARN", f"{detail}, but {stats.frozen_frames} repeated the previous frame"
        if fps < 0.5 * self.spec.fps:
            return "WARN", f"only {fps:.1f} fps (configured {self.spec.fps}); USB bandwidth/power?"
        if stats.read_failures:
            return "WARN", f"{detail}, with {stats.read_failures} dropped reads"
        return "PASS", f"{detail} (0 blank, 0 frozen)"


def render_tiles(workers: list[CameraWorker], *, scale: float = 2.0) -> np.ndarray:
    """Lay every camera side by side with its live name/fps/status banner."""
    tiles: list[np.ndarray] = []
    height = max(w.spec.height for w in workers)
    for worker in workers:
        frame = worker.latest()
        if frame is None:
            frame = np.zeros((worker.spec.height, worker.spec.width, 3), dtype=np.uint8)
            status, color = "NO SIGNAL", (60, 60, 220)
        elif worker.stats.dead:
            status, color = "FEED LOST", (60, 60, 220)
        else:
            status, color = f"{worker.stats.fps():.1f} fps", (120, 220, 120)
        if frame.shape[0] != height:
            width = int(frame.shape[1] * height / frame.shape[0])
            frame = cv2.resize(frame, (width, height))
        frame = frame.copy()
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 26), (0, 0, 0), -1)
        cv2.putText(
            frame,
            f"{worker.spec.key}  {status}",
            (8, 19),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), (70, 70, 70), 1)
        tiles.append(frame)

    canvas = np.hstack(tiles)
    if scale != 1.0:
        canvas = cv2.resize(
            canvas,
            (int(canvas.shape[1] * scale), int(canvas.shape[0] * scale)),
            interpolation=cv2.INTER_NEAREST,
        )
    return canvas


def build_parser(description: str) -> argparse.ArgumentParser:
    """CLI options shared by the Pi-side camera checks."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--view",
        choices=("none", "mjpeg", "window"),
        default="none",
        help="none = just check and save frames; mjpeg = watch from your PC in a browser.",
    )
    parser.add_argument("--http-port", type=int, default=8094, help="Port for the MJPEG view.")
    parser.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        help="How long to sample (0 = run until Ctrl+C).",
    )
    parser.add_argument("--scale", type=float, default=2.0, help="Preview zoom factor.")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Requested frame width.")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="Requested frame height.")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="Requested frame rate.")
    parser.add_argument(
        "--fourcc", default="", help="Pixel format to request (e.g. MJPG); empty = driver default."
    )
    parser.add_argument(
        "--device",
        action="append",
        metavar="NAME=PATH",
        help="Override a camera's device path, e.g. --device front_left=/dev/video6. Repeatable.",
    )
    parser.add_argument(
        "--save-dir",
        default="camera_health",
        help="Where to write one final frame per camera ('' to skip).",
    )
    return parser


def run_device_check(specs: list[CameraSpec], title: str, args: argparse.Namespace) -> int:
    """Open every camera directly, sample it, then print a PASS/FAIL table."""
    if args.view == "window" and not gui_available():
        print(
            "[check] FAIL  --view window needs a GUI OpenCV build; this package uses opencv-python-headless"
        )
        print("[check]       use --view mjpeg to watch it in a browser instead")
        return 1

    print(f"[check] {title}")
    print("[check] opening the devices directly - sourccey-host must be STOPPED")
    workers = [CameraWorker(spec) for spec in specs]
    for worker in workers:
        spec = worker.spec
        if worker.open():
            print(
                f"[check] {spec.key:<12} OPEN  {spec.path}  "
                f"requested={spec.width}x{spec.height}@{spec.fps} "
                f"negotiated={worker.stats.negotiated}"
            )
            worker.start()
        else:
            print(f"[check] {spec.key:<12} FAIL  {worker.stats.open_error}")

    live = [w for w in workers if w.stats.opened]
    server: MjpegServer | None = None
    if live and args.view == "mjpeg":
        server = MjpegServer(args.http_port, title)
        server.start()
        print(f"[check] open http://{lan_ip()}:{args.http_port}/ on your PC to watch the feeds")
    if live:
        if args.seconds > 0:
            print(f"[check] sampling for {args.seconds:.0f}s...")
        else:
            print("[check] sampling until you press Ctrl+C...")

    start = time.monotonic()
    next_heartbeat = start + 2.0
    try:
        while live:
            now = time.monotonic()
            if args.seconds > 0 and (now - start) >= args.seconds:
                break
            if now >= next_heartbeat:
                next_heartbeat = now + 2.0
                summary = "  ".join(f"{w.spec.key}={w.stats.fps():.1f}fps" for w in live)
                print(f"[check] live  {summary}", flush=True)
            if args.view == "none":
                time.sleep(0.1)
                continue
            canvas = render_tiles(live, scale=args.scale)
            if server is not None:
                server.publish(canvas)
            else:
                cv2.imshow(title, canvas)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
            time.sleep(0.03)
    except KeyboardInterrupt:
        print()
    finally:
        if args.save_dir:
            out_dir = Path(args.save_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            for worker in live:
                frame = worker.latest()
                if frame is not None:
                    path = out_dir / f"{worker.spec.key}.jpg"
                    cv2.imwrite(str(path), frame)
                    print(f"[check] saved {path}")
        for worker in workers:
            worker.stop()
        if server is not None:
            server.stop()
        if args.view == "window":
            with contextlib.suppress(Exception):
                cv2.destroyAllWindows()

    print()
    print(f"[check] ==== {title}: results ====")
    failed = 0
    for worker in workers:
        status, reason = worker.verdict()
        failed += status == "FAIL"
        print(f"[check] {status:<4} {worker.spec.key:<12} {reason}")
    print(f"[check] {len(workers) - failed}/{len(workers)} cameras healthy")
    return 1 if failed else 0

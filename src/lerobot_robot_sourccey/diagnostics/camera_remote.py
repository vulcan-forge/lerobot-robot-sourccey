"""Shared observation receiver and health checks for remote camera diagnostics.

These checks run **on your control PC** and connect to the robot the same way
the teleop client does: a ZMQ socket to `sourccey-host` on the Pi, decoding
the same protobuf observation packets. So `sourccey-host` must be running on
the robot, exactly as it is for teleop.

The connection here is **strictly passive**: only the observation socket is
opened, never the command socket, so these scripts physically cannot move the
base or the arms.

One caveat worth knowing: the host's observation socket is a ZMQ PUSH, which
round-robins between connected receivers. If a teleop session is running at the
same time, the two of you split the frames. Run these checks with nothing else
connected.

Per the stack's hard directives there are **no silent fallbacks**: a camera the
host never publishes, or one whose frames are blank or frozen, is reported as
FAIL with the reason, never quietly skipped.
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
import zmq

from lerobot_robot_sourccey.robots.protobuf.generated import sourccey_pb2
from lerobot_robot_sourccey.robots.protobuf.sourccey_protobuf import SourcceyProtobuf

from .preview import MjpegServer, gui_available

# A frame whose pixel spread is below this is effectively a blank sensor output:
# lens cap, dead exposure, or a stream that opened but never delivered light.
BLANK_FRAME_STD = 1.5
# Fraction of frames that may be identical to their predecessor before the feed
# is called frozen (a stalled camera keeps republishing its last buffer).
FROZEN_FRAME_RATIO = 0.9
# Camera frames older than this are stale rather than live.
STALE_AFTER_S = 2.0


@dataclass
class CameraStats:
    """Live health counters for one camera, filled in by the receive thread."""

    frames: int = 0
    frozen_frames: int = 0
    blank_frames: int = 0
    last_rx: float | None = None
    last_checksum: int | None = None
    stamps: deque[float] = field(default_factory=lambda: deque(maxlen=90))

    def fps(self) -> float:
        """Rolling frame rate over the recent window (0.0 before two frames)."""
        if len(self.stamps) < 2:
            return 0.0
        span = self.stamps[-1] - self.stamps[0]
        return (len(self.stamps) - 1) / span if span > 0 else 0.0

    def age_s(self) -> float | None:
        return None if self.last_rx is None else time.monotonic() - self.last_rx


class ObservationSubscriber:
    """Passive receiver for the host's observation stream.

    Mirrors what `SourcceyClient` does to read frames — PULL socket, protobuf
    decode — minus every command path, so this can never actuate the robot.
    """

    def __init__(self, remote_ip: str, port: int, *, connect_timeout_s: float = 10.0) -> None:
        self.remote_ip = remote_ip
        self.port = int(port)
        self.connect_timeout_s = float(connect_timeout_s)
        self._converter = SourcceyProtobuf()
        self._context: zmq.Context | None = None
        self._socket: zmq.Socket | None = None
        self._frames: dict[str, np.ndarray] = {}
        self._stats: dict[str, CameraStats] = {}
        self._state: dict[str, float] = {}
        self._packets = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> str:
        return f"tcp://{self.remote_ip}:{self.port}"

    def connect(self) -> None:
        """Open the observation socket and wait for the first packet.

        Raises TimeoutError if the host never sends — that means the host is not
        running (or is unreachable), which is a real failure, not something to
        paper over with an empty view.
        """
        if self._socket is not None:
            raise RuntimeError("Observation subscriber is already connected")
        self._stop.clear()
        try:
            self._context = zmq.Context()
            socket = self._context.socket(zmq.PULL)
            self._socket = socket
            # CONFLATE keeps only the newest observation: a diagnostic must show the
            # CURRENT view, never a backlog queued while we were drawing.
            socket.setsockopt(zmq.CONFLATE, 1)
            socket.connect(self.endpoint)

            poller = zmq.Poller()
            poller.register(socket, zmq.POLLIN)
            socks = dict(poller.poll(int(self.connect_timeout_s * 1000)))
            if socks.get(socket) != zmq.POLLIN:
                self.close()
                raise TimeoutError(
                    f"no observation packet from {self.endpoint} within "
                    f"{self.connect_timeout_s:.0f}s - is sourccey-host running on the robot?"
                )
            self._ingest(socket.recv())
            self._thread = threading.Thread(target=self._run, daemon=True, name="sourccey_check_rx")
            self._thread.start()
        except BaseException:
            self.close()
            raise

    def _run(self) -> None:
        socket = self._socket
        if socket is None:
            return
        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)
        while not self._stop.is_set():
            try:
                if dict(poller.poll(100)).get(socket) != zmq.POLLIN:
                    continue
                self._ingest(socket.recv())
            except zmq.ZMQError:
                return

    def _ingest(self, payload: bytes) -> None:
        """Decode one observation packet and update per-camera health counters."""
        robot_state = sourccey_pb2.SourcceyRobotState()
        robot_state.ParseFromString(payload)
        observation = self._converter.protobuf_to_observation(robot_state)
        if observation is None:
            return

        now = time.monotonic()
        with self._lock:
            self._packets += 1
            for key, value in observation.items():
                if not isinstance(value, np.ndarray):
                    self._state[key] = value
                    continue
                stats = self._stats.setdefault(key, CameraStats())
                # A frozen camera keeps republishing the same buffer, and a dead
                # sensor publishes a flat frame; both "arrive fine" but are not
                # vision, so count them explicitly rather than trusting arrival.
                checksum = int(value[::8, ::8].sum())
                if stats.last_checksum is not None and checksum == stats.last_checksum:
                    stats.frozen_frames += 1
                stats.last_checksum = checksum
                if float(value.std()) < BLANK_FRAME_STD:
                    stats.blank_frames += 1
                stats.frames += 1
                stats.last_rx = now
                stats.stamps.append(now)
                self._frames[key] = value

    def latest(self, key: str) -> np.ndarray | None:
        with self._lock:
            frame = self._frames.get(key)
            return None if frame is None else frame.copy()

    def stats(self, key: str) -> CameraStats:
        with self._lock:
            return self._stats.get(key, CameraStats())

    def state(self) -> dict[str, float]:
        """Latest non-image observation values (joint positions, base velocity, z)."""
        with self._lock:
            return dict(self._state)

    def published_keys(self) -> list[str]:
        """Camera names the host has actually sent at least one frame for."""
        with self._lock:
            return sorted(self._stats.keys())

    def packets(self) -> int:
        with self._lock:
            return self._packets

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._socket is not None:
            self._socket.close(0)
            self._socket = None
        if self._context is not None:
            self._context.term()
            self._context = None


def verdict_for(key: str, stats: CameraStats, expected_fps: float) -> tuple[str, str]:
    """Return (PASS|WARN|FAIL, reason) for one camera."""
    if stats.frames == 0:
        return "FAIL", (
            "the host published no frames for this camera "
            "(not opened on the robot, or not in its camera config)"
        )
    age = stats.age_s()
    if age is not None and age > STALE_AFTER_S:
        return "FAIL", f"frames stopped {age:.1f}s ago — the camera dropped out mid-run"
    # This is the load-bearing check. When a camera read fails on the robot, the
    # host does NOT drop the key - it publishes np.zeros() to keep the observation
    # schema stable (see Sourccey.get_observation). A dead camera therefore arrives
    # at full frame rate and would otherwise look perfectly healthy.
    if stats.blank_frames >= stats.frames:
        return "FAIL", (
            f"all {stats.frames} frames are black/flat - the host is substituting blank "
            "frames because the camera read is failing on the robot"
        )
    if stats.frames > 10 and stats.frozen_frames > FROZEN_FRAME_RATIO * stats.frames:
        return "FAIL", f"feed is frozen ({stats.frozen_frames}/{stats.frames} identical frames)"

    fps = stats.fps()
    detail = f"{stats.frames} frames at {fps:.1f} fps"
    # Intermittent failures are the same mechanism, just partial: some real frames,
    # some host-substituted black ones. Silently passing those hides a dying camera.
    if stats.blank_frames:
        return "WARN", (
            f"{stats.blank_frames}/{stats.frames} frames were black - the camera is "
            "intermittently failing to read on the robot (check its USB cable/power)"
        )
    if stats.frozen_frames:
        return "WARN", (
            f"{detail}, but {stats.frozen_frames} were identical to the previous frame - "
            "the feed is intermittently stalling"
        )
    if expected_fps > 0 and fps < 0.5 * expected_fps:
        return "WARN", (
            f"only {fps:.1f} fps (host camera is configured for {expected_fps:.0f}); "
            "USB bandwidth on the Pi, or another client is sharing the stream"
        )
    return "PASS", f"{detail} (0 blank, 0 frozen)"


def render_tiles(
    subscriber: ObservationSubscriber, keys: tuple[str, ...], *, scale: float = 2.0
) -> np.ndarray:
    """Lay every expected camera side by side with its live name/fps/status banner."""
    tiles: list[np.ndarray] = []
    frames = {key: subscriber.latest(key) for key in keys}
    height = max((f.shape[0] for f in frames.values() if f is not None), default=240)

    for key in keys:
        frame = frames[key]
        stats = subscriber.stats(key)
        age = stats.age_s()
        if frame is None:
            frame = np.zeros((height, int(height * 4 / 3), 3), dtype=np.uint8)
            status, color = "NOT PUBLISHED", (60, 60, 220)
        elif age is not None and age > STALE_AFTER_S:
            status, color = f"STALE {age:.1f}s", (60, 60, 220)
        else:
            status, color = f"{stats.fps():.1f} fps", (120, 220, 120)
        if frame.shape[0] != height:
            width = int(frame.shape[1] * height / frame.shape[0])
            frame = cv2.resize(frame, (width, height))
        frame = frame.copy()
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 26), (0, 0, 0), -1)
        cv2.putText(
            frame,
            f"{key}  {status}",
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
    """CLI options shared by both camera-check scripts."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--remote-ip",
        required=True,
        help="IP of the robot Pi running sourccey-host (same value teleop uses).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5556,
        help="Host observation port (SourcceyClientConfig.port_zmq_observations).",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for the first observation packet before failing.",
    )
    parser.add_argument(
        "--view",
        choices=("auto", "window", "mjpeg", "none"),
        default="auto",
        help="auto = local window on a desktop machine, else a browser MJPEG stream.",
    )
    parser.add_argument("--http-port", type=int, default=8091, help="Port for the MJPEG view.")
    parser.add_argument(
        "--seconds",
        type=float,
        default=0.0,
        help="Stop after N seconds (0 = run until Ctrl+C / 'q').",
    )
    parser.add_argument("--scale", type=float, default=2.0, help="Preview zoom factor.")
    parser.add_argument(
        "--save-dir",
        default=None,
        help="Write one final frame per camera into this directory.",
    )
    return parser


NO_GUI_HINT = "this OpenCV build has no GUI support (the package uses opencv-python-headless, so cv2.imshow cannot draw)"


def resolve_view(view: str) -> str:
    """Pick the preview transport, and say so when it is not what was implied."""
    if view == "window" and not gui_available():
        # An explicit --view window that cannot work is an error, not something
        # to quietly reroute: the user asked for a specific thing.
        raise RuntimeError(
            f"--view window was requested but {NO_GUI_HINT}. "
            "Use --view mjpeg to watch in a browser, or install the GUI build "
            "(`uv pip install opencv-python`) in a separate environment."
        )
    if view != "auto":
        return view
    if not gui_available():
        print(f"[check] NOTE  {NO_GUI_HINT}; serving the preview over HTTP instead")
        return "mjpeg"
    if os.name == "nt" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return "window"
    return "mjpeg"


def run_camera_check(
    keys: tuple[str, ...],
    expected_fps: dict[str, float],
    title: str,
    args: argparse.Namespace,
) -> int:
    """Stream the named cameras from the robot, then print a PASS/FAIL table."""
    print(f"[check] {title}")
    try:
        view = resolve_view(args.view)
    except RuntimeError as exc:
        print(f"[check] FAIL  {exc}")
        return 1
    subscriber = ObservationSubscriber(args.remote_ip, args.port, connect_timeout_s=args.connect_timeout)

    print(f"[check] connecting to the robot at {subscriber.endpoint} (passive: observations only)")
    try:
        subscriber.connect()
    except TimeoutError as exc:
        print(f"[check] FAIL  {exc}")
        print("[check]       start it on the Pi with: uv run sourccey-host")
        return 1
    except zmq.ZMQError as exc:
        print(f"[check] FAIL  could not open {subscriber.endpoint}: {exc}")
        return 1

    print(f"[check] connected; expecting cameras: {', '.join(keys)}")
    server: MjpegServer | None = None
    if view == "mjpeg":
        server = MjpegServer(args.http_port, title)
        server.start()
        print(f"[check] open http://127.0.0.1:{args.http_port}/ to watch the feeds")
    elif view == "window":
        print("[check] press 'q' in the preview window to stop")
    if args.seconds > 0:
        print(f"[check] running for {args.seconds:.0f}s, then printing results")
    else:
        print("[check] running until you press Ctrl+C (or pass --seconds N to time-box it)")

    start = time.monotonic()
    # A live heartbeat: without it the terminal looks frozen for the whole run,
    # and there is no way to tell "connected and streaming" from "stalled".
    next_heartbeat = start + 2.0
    try:
        while True:
            now = time.monotonic()
            if args.seconds > 0 and (now - start) >= args.seconds:
                break
            if now >= next_heartbeat:
                next_heartbeat = now + 2.0
                live_summary = "  ".join(
                    f"{key}={subscriber.stats(key).fps():.1f}fps"
                    if subscriber.stats(key).frames
                    else f"{key}=--"
                    for key in keys
                )
                # flush: the heartbeat is worthless if it sits in a pipe buffer.
                print(f"[check] live  {live_summary}   ({subscriber.packets()} packets)", flush=True)
            if view == "none":
                time.sleep(0.1)
                continue
            canvas = render_tiles(subscriber, keys, scale=args.scale)
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
            for key in keys:
                frame = subscriber.latest(key)
                if frame is not None:
                    path = out_dir / f"{key}.jpg"
                    cv2.imwrite(str(path), frame)
                    print(f"[check] saved {path}")
        published = subscriber.published_keys()
        packets = subscriber.packets()
        results = [
            (key, *verdict_for(key, subscriber.stats(key), expected_fps.get(key, 0.0))) for key in keys
        ]
        subscriber.close()
        if server is not None:
            server.stop()
        if view == "window":
            # Never let teardown raise: a second exception here would mask
            # whatever actually went wrong in the loop above.
            with contextlib.suppress(Exception):
                cv2.destroyAllWindows()

    print()
    print(f"[check] ==== {title}: results ====")
    print(f"[check] {packets} observation packets received from {args.remote_ip}")
    print(f"[check] cameras the host is publishing: {', '.join(published) or '(none)'}")
    failed = 0
    for key, status, reason in results:
        failed += status == "FAIL"
        print(f"[check] {status:<4} {key:<12} {reason}")
    print(f"[check] {len(results) - failed}/{len(results)} cameras healthy")
    return 1 if failed else 0

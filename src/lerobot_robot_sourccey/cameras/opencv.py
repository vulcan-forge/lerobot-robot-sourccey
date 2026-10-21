"""Sourccey's recoverable OpenCV camera, registered through the standard device factory."""

import logging
import math
import time
from dataclasses import dataclass

import cv2

from lerobot.cameras import CameraConfig
from lerobot.cameras.opencv import OpenCVCamera, OpenCVCameraConfig
from lerobot.utils.errors import DeviceNotConnectedError

logger = logging.getLogger(__name__)


@CameraConfig.register_subclass("sourccey_opencv")
@dataclass
class SourcceyOpenCVCameraConfig(OpenCVCameraConfig):
    """OpenCV settings with cancellable camera recovery enabled by default."""

    auto_reconnect: bool = True
    max_consecutive_read_failures: int = 2
    fast_reconnect_interval_s: float = 0.05
    fast_reconnect_window_s: float = 2.0
    reconnect_interval_s: float = 0.5

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            isinstance(self.max_consecutive_read_failures, bool)
            or not isinstance(self.max_consecutive_read_failures, int)
            or self.max_consecutive_read_failures < 1
        ):
            raise ValueError("max_consecutive_read_failures must be a positive integer")
        for name in ("fast_reconnect_interval_s", "fast_reconnect_window_s", "reconnect_interval_s"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


class SourcceyOpenCVCamera(OpenCVCamera):
    """Recover capture after unplugging while preserving upstream image handling."""

    config_class = SourcceyOpenCVCameraConfig

    def __init__(self, config: SourcceyOpenCVCameraConfig) -> None:
        super().__init__(config)

    def _release_capture(self) -> None:
        capture, self.videocapture = self.videocapture, None
        if capture is not None:
            capture.release()

    def _recover(self, reason: Exception) -> bool:
        stop = self.stop_event
        if not self.config.auto_reconnect or stop is None or stop.is_set():
            return False
        logger.warning("%s reconnecting after read failure: %s", self, reason)
        self._release_capture()
        with self.frame_lock:
            self.latest_frame = None
            self.latest_timestamp = None
            self.new_frame_event.clear()
        started = time.monotonic()
        while not stop.is_set():
            try:
                self.videocapture = cv2.VideoCapture(self.index_or_path, self.backend)
                if not self.videocapture.isOpened():
                    raise ConnectionError(f"Failed to reopen {self}")
                self._configure_capture_settings()
                if stop.is_set():
                    self._release_capture()
                    return False
                logger.info("%s reconnected", self)
                return True
            except Exception as exc:
                self._release_capture()
                logger.debug("%s reconnect attempt failed: %s", self, exc)
                delay = (
                    self.config.fast_reconnect_interval_s
                    if time.monotonic() - started < self.config.fast_reconnect_window_s
                    else self.config.reconnect_interval_s
                )
                stop.wait(delay)
        return False

    def _read_loop(self) -> None:
        stop = self.stop_event
        if stop is None:
            raise RuntimeError("Camera read loop requires a stop event")
        failures = 0
        while not stop.is_set():
            try:
                frame = self._postprocess_image(self._read_from_hardware())
                with self.frame_lock:
                    self.latest_frame = frame
                    self.latest_timestamp = time.perf_counter()
                self.new_frame_event.set()
                failures = 0
            except Exception as exc:
                if stop.is_set():
                    break
                failures += 1
                if (
                    not isinstance(exc, DeviceNotConnectedError)
                    and failures < self.config.max_consecutive_read_failures
                ):
                    continue
                if not self._recover(exc):
                    if stop.is_set():
                        break
                    raise RuntimeError(f"{self} exceeded maximum consecutive read failures") from exc
                failures = 0

    def _cleanup_resources(self) -> None:
        # Capture ownership may change during recovery. Release the current capture
        # after the worker exits, rather than the pre-join snapshot used upstream.
        stop, thread = self.stop_event, self.thread
        if stop is not None:
            stop.set()
        if thread is not None:
            thread.join(timeout=2.0)
        self._release_capture()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
            if thread.is_alive():
                raise RuntimeError(f"{self} camera read thread did not stop")
        self.thread = None
        self.stop_event = None
        with self.frame_lock:
            self.latest_frame = None
            self.latest_timestamp = None
            self.new_frame_event.clear()

    def disconnect(self) -> None:
        self._cleanup_resources()

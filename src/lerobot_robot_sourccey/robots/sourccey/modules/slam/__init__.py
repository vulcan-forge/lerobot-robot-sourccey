# Copyright 2025 The HuggingFace Inc. team. All rights reserved.
# Copyright 2025 Vulcan Robotics, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import logging
import time
from typing import Any, Optional

import cv2
import numpy as np
import zmq

from .config import SlamInputConfig


def create_slam_pub_socket(zmq_context: zmq.Context, endpoint: str) -> zmq.Socket:
    socket = zmq_context.socket(zmq.PUB)
    socket.setsockopt(zmq.LINGER, 0)
    try:
        socket.bind(endpoint)
    except zmq.ZMQError as e:
        socket.close(0)
        raise RuntimeError(f"Failed to bind SLAM input publisher at {endpoint}: {e}") from e
    return socket


def close_slam_pub_socket(socket: Optional[zmq.Socket]) -> None:
    if socket is not None:
        socket.close(0)


class SlamInputPublisher:
    """Builds and publishes `slam_input.v1` packets from Sourccey observations."""

    def __init__(
        self,
        *,
        source_id: str,
        stereo_left_key: str,
        stereo_right_key: str,
        jpeg_quality: int,
        warn_log_interval_s: float = 5.0,
    ) -> None:
        self._source_id = source_id
        self._stereo_left_key = stereo_left_key
        self._stereo_right_key = stereo_right_key
        self._jpeg_quality = int(np.clip(jpeg_quality, 1, 100))
        self._warn_log_interval_s = warn_log_interval_s

        self._camera_frame_ids: dict[str, int] = {}
        self._warn_last_ts: dict[str, float] = {}
        self._warn_suppressed: dict[str, int] = {}

    def publish(
        self,
        *,
        socket: Optional[zmq.Socket],
        observation: dict[str, Any],
        frames: dict[str, np.ndarray],
    ) -> None:
        payload = self.build_packet(observation=observation, frames=frames)
        if payload is None or socket is None:
            return
        try:
            socket.send(payload, flags=zmq.NOBLOCK)
        except zmq.Again:
            logging.debug("Dropping SLAM input packet, no subscriber connected.")
        except Exception as e:
            self.log_warning_throttled(
                "slam_send_failed",
                f"Failed to publish SLAM input packet: {e}",
            )

    def build_packet(
        self, *, observation: dict[str, Any], frames: dict[str, np.ndarray]
    ) -> Optional[bytes]:
        left_key = self._stereo_left_key
        right_key = self._stereo_right_key
        required_keys = (left_key, right_key)

        missing_keys = [key for key in required_keys if key not in frames or frames[key] is None]
        if missing_keys:
            self.log_warning_throttled(
                "slam_missing_stereo",
                (
                    "Skipping SLAM input publish: missing required stereo frames "
                    f"{missing_keys} (configured left={left_key}, right={right_key})."
                ),
            )
            return None

        cameras_payload: dict[str, dict[str, Any]] = {}
        now_ns = time.monotonic_ns()
        for cam_name, frame in frames.items():
            if not isinstance(frame, np.ndarray):
                continue

            ok, encoded_jpg = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), int(self._jpeg_quality)],
            )
            if not ok or encoded_jpg is None:
                self.log_warning_throttled(
                    f"slam_jpeg_encode_failed:{cam_name}",
                    f"Skipping SLAM camera frame '{cam_name}': JPEG encoding failed.",
                )
                if cam_name in required_keys:
                    return None
                continue

            frame_id = self._camera_frame_ids.get(cam_name, 0) + 1
            self._camera_frame_ids[cam_name] = frame_id

            cameras_payload[cam_name] = {
                "frame_id": frame_id,
                "capture_monotonic_ns": now_ns,
                "jpeg_b64": base64.b64encode(encoded_jpg.tobytes()).decode("ascii"),
            }

        if left_key not in cameras_payload or right_key not in cameras_payload:
            self.log_warning_throttled(
                "slam_missing_required_encoded",
                (
                    "Skipping SLAM input publish: required stereo cameras were not encoded "
                    f"(left={left_key in cameras_payload}, right={right_key in cameras_payload})."
                ),
            )
            return None

        packet = {
            "schema": "slam_input.v1",
            "source": f"sourccey_client:{self._source_id}",
            "host_monotonic_ns": now_ns,
            "base_velocity": {
                "x.vel": float(observation.get("x.vel", 0.0)),
                "y.vel": float(observation.get("y.vel", 0.0)),
                "theta.vel": float(observation.get("theta.vel", 0.0)),
            },
            "stereo_left": left_key,
            "stereo_right": right_key,
            "imu_samples": [],
            "cameras": cameras_payload,
        }
        return json.dumps(packet, separators=(",", ":")).encode("utf-8")

    def log_warning_throttled(self, key: str, message: str) -> None:
        now = time.monotonic()
        last_ts = self._warn_last_ts.get(key, 0.0)
        elapsed = now - last_ts
        if elapsed >= self._warn_log_interval_s:
            suppressed = self._warn_suppressed.get(key, 0)
            if suppressed > 0:
                logging.warning("%s (suppressed %d similar warnings)", message, suppressed)
            else:
                logging.warning("%s", message)
            self._warn_last_ts[key] = now
            self._warn_suppressed[key] = 0
        else:
            self._warn_suppressed[key] = self._warn_suppressed.get(key, 0) + 1


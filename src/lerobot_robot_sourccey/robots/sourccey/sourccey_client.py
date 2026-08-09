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
from functools import cached_property
import time
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np
import zmq

from lerobot.utils.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError

from lerobot.robots.robot import Robot
from .config_sourccey import SourcceyClientConfig
from .modules.slam import (
    SlamInputPublisher,
    close_slam_pub_socket,
    create_slam_pub_socket,
)

# Import protobuf modules
from ..protobuf.generated import sourccey_pb2
from ..protobuf.sourccey_protobuf import SourcceyProtobuf

class SourcceyClient(Robot):
    config_class = SourcceyClientConfig
    name = "sourccey_client"

    def __init__(self, config: SourcceyClientConfig):
        super().__init__(config)
        self.config = config
        self.id = config.id
        self.robot_type = config.type

        self.remote_ip = config.remote_ip
        self.port_zmq_cmd = config.port_zmq_cmd
        self.port_zmq_observations = config.port_zmq_observations
        slam_cfg = config.slam
        self.slam_input_enabled = slam_cfg.input_enabled
        self.slam_input_endpoint = slam_cfg.input_endpoint
        self.slam_stereo_left_key = slam_cfg.stereo_left_key
        self.slam_stereo_right_key = slam_cfg.stereo_right_key
        self.slam_jpeg_quality = int(np.clip(slam_cfg.jpeg_quality, 1, 100))

        self.teleop_keys = config.teleop_keys

        self.polling_timeout_ms = config.polling_timeout_ms
        self.wait_for_fresh_observation = config.wait_for_fresh_observation
        self.fresh_observation_timeout_ms = config.fresh_observation_timeout_ms
        self.log_no_data_timeouts = config.log_no_data_timeouts
        self.no_data_log_interval_s = max(0.0, float(config.no_data_log_interval_s))
        self.connect_timeout_s = config.connect_timeout_s

        self.zmq_context = None
        self.zmq_cmd_socket = None
        self.zmq_observation_socket = None
        self.zmq_slam_input_socket = None

        self.last_frames = {}
        self.last_remote_state = {}
        self._last_sent_action: dict[str, Any] = {}
        self._slam_input_publisher = SlamInputPublisher(
            source_id=self.id,
            stereo_left_key=self.slam_stereo_left_key,
            stereo_right_key=self.slam_stereo_right_key,
            jpeg_quality=self.slam_jpeg_quality,
        )

        # Define three speed levels and a current index
        self.speed_levels = [
            {"x": 0.8, "y": 0.8, "z": 1.0, "theta": 0.8},
            {"x": 0.9, "y": 0.9, "z": 1.0, "theta": 0.9},
            {"x": 1.0, "y": 1.0, "z": 1.0, "theta": 1.0},
        ]
        self.speed_index = 1  # Start at medium speed (0.9)

        self._is_connected = False
        self.logs = {}

        # Initialize protobuf converter
        self.protobuf_converter = SourcceyProtobuf()

        # Per-arm untorque toggle state and key edge detection
        self.untorque_left_active = False
        self.untorque_right_active = False
        self._prev_keys: set[str] = set()

        # Time of last command
        self._last_cmd_t = time.monotonic()

        # Base movement smoothing
        self._slew_time_s_levels = [0.25, 0.25, 1.0]
        self._x_deadbane = 0.02
        self._y_deadbane = 0.02

        # max change in x.vel per second (tune this)
        self._x_accel_levels = [7.0, 5.0, 3.0]   # units: (x.vel units) / s
        self._x_decel_levels = [7.0, 5.0, 3.0]   # allow faster slowing down than speeding up (optional)
        self._x_cmd_smoothed = 0.0
        self._y_accel_levels = [7.0, 5.0, 3.0]   # units: (y.vel units) / s
        self._y_decel_levels = [7.0, 5.0, 3.0]   # allow faster slowing down than speeding up (optional)
        self._y_cmd_smoothed = 0.0

        # Z Position Control
        # Z uses a fixed 25 position units/s at every base speed level.
        self._z_min = -100.0
        self._z_max = 100.0
        self._z_full_travel_s = max(0.1, float(config.z_teleop_full_travel_s))
        self._z_units_per_s = (self._z_max - self._z_min) / self._z_full_travel_s
        self._z_max_target_step = max(0.1, float(config.z_teleop_max_target_step))

        # Stored target position. It is initialized from the first remote sensor
        # observation instead of assuming the actuator starts at +100.
        self._z_pos_cmd = 0.0
        self._z_pos_cmd_initialized = False

        # Log-throttle repeated poll timeouts to avoid terminal spam in teleop loops.
        self._no_data_log_interval_s = self.no_data_log_interval_s
        self._last_no_data_log_ts = 0.0
        self._suppressed_no_data_logs = 0

    ###################################################################
    # Properties and Attributes
    ###################################################################
    @cached_property
    def _state_ft(self) -> dict[str, type]:
        return dict.fromkeys(
            (
                "left_shoulder_pan.pos",
                "left_shoulder_lift.pos",
                "left_elbow_flex.pos",
                "left_wrist_flex.pos",
                "left_wrist_roll.pos",
                "left_gripper.pos",
                "right_shoulder_pan.pos",
                "right_shoulder_lift.pos",
                "right_elbow_flex.pos",
                "right_wrist_flex.pos",
                "right_wrist_roll.pos",
                "right_gripper.pos",
                "z.pos",
                "x.vel",
                "y.vel",
                "theta.vel",
                "z.vel",
            ),
            float,
        )

    @cached_property
    def _state_order(self) -> tuple[str, ...]:
        return tuple(self._state_ft.keys())

    @cached_property
    def _cameras_ft(self) -> dict[str, tuple[int, int, int]]:
        return {name: (cfg.height, cfg.width, 3) for name, cfg in self.config.cameras.items()}

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        return {**self._state_ft, **self._cameras_ft}

    @cached_property
    def action_features(self) -> dict[str, type]:
        return {
            **self._state_ft,
            "untorque_left": bool,
            "untorque_right": bool,
        }

    @cached_property
    def cameras(self) -> dict[str, Any]:
        """Expose configured remote cameras for CLI compatibility.

        SourcceyClient receives camera frames over the network (it does not own
        local camera device objects), but several generic scripts inspect
        ``len(robot.cameras)`` to size image-writer workers.
        """
        return self.config.cameras

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def is_calibrated(self) -> bool:
        pass

    ###################################################################
    # Event Management
    ###################################################################
    def on_key_down(self, key_char: str) -> None:
        if key_char == self.teleop_keys["speed_up"]:
            self.speed_index = min(self.speed_index + 1, len(self.speed_levels) - 1)
            print(f"Speed index: {self.speed_index}")
        elif key_char == self.teleop_keys["speed_down"]:
            self.speed_index = max(self.speed_index - 1, 0)
            print(f"Speed index: {self.speed_index}")

    ###################################################################
    # Connection Management
    ###################################################################
    def connect(self) -> None:
        """Establishes ZMQ sockets with the remote mobile robot"""

        if self._is_connected:
            raise DeviceAlreadyConnectedError(
                "SourcceyClient is already connected. Do not run `robot.connect()` twice."
            )

        try:
            self.zmq_context = zmq.Context()
            self.zmq_cmd_socket = self.zmq_context.socket(zmq.PUSH)
            zmq_cmd_locator = f"tcp://{self.remote_ip}:{self.port_zmq_cmd}"
            self.zmq_cmd_socket.connect(zmq_cmd_locator)
            self.zmq_cmd_socket.setsockopt(zmq.CONFLATE, 1)

            self.zmq_observation_socket = self.zmq_context.socket(zmq.PULL)
            zmq_observations_locator = f"tcp://{self.remote_ip}:{self.port_zmq_observations}"
            self.zmq_observation_socket.connect(zmq_observations_locator)
            self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)

            if self.slam_input_enabled:
                self.zmq_slam_input_socket = create_slam_pub_socket(
                    self.zmq_context, self.slam_input_endpoint
                )

            poller = zmq.Poller()
            poller.register(self.zmq_observation_socket, zmq.POLLIN)
            socks = dict(poller.poll(self.connect_timeout_s * 1000))
            if self.zmq_observation_socket not in socks or socks[self.zmq_observation_socket] != zmq.POLLIN:
                raise DeviceNotConnectedError("Timeout waiting for Sourccey Host to connect expired.")

            self._is_connected = True
        except Exception:
            if self.zmq_slam_input_socket is not None:
                close_slam_pub_socket(self.zmq_slam_input_socket)
                self.zmq_slam_input_socket = None
            if self.zmq_observation_socket is not None:
                self.zmq_observation_socket.close(0)
                self.zmq_observation_socket = None
            if self.zmq_cmd_socket is not None:
                self.zmq_cmd_socket.close(0)
                self.zmq_cmd_socket = None
            if self.zmq_context is not None:
                self.zmq_context.term()
                self.zmq_context = None
            raise

    def calibrate(self) -> None:
        pass

    def configure(self):
        pass

    def _send_base_stop_command(self) -> bool:
        """
        Best-effort final command before disconnect.

        Stops base motion while resending existing arm targets. Z is omitted so the
        host keeps its current target. If a complete arm state is unavailable, send
        nothing and let the host watchdog stop the base.
        """
        stop_action: dict[str, Any] = {
            "x.vel": 0.0,
            "y.vel": 0.0,
            "theta.vel": 0.0,
        }
        arm_keys = tuple(
            key for key in self._state_order if key.startswith(("left_", "right_")) and key.endswith(".pos")
        )
        for key in arm_keys:
            if key in self._last_sent_action:
                stop_action[key] = self._last_sent_action[key]
            elif key in self.last_remote_state:
                stop_action[key] = self.last_remote_state[key]
            else:
                logging.debug("Skipping final base stop: no safe hold target for %s.", key)
                return False

        stop_action["untorque_left"] = bool(
            self._last_sent_action.get("untorque_left", self.untorque_left_active)
        )
        stop_action["untorque_right"] = bool(
            self._last_sent_action.get("untorque_right", self.untorque_right_active)
        )
        robot_action = self.protobuf_converter.action_to_protobuf(stop_action)
        self.zmq_cmd_socket.send(robot_action.SerializeToString(), flags=zmq.NOBLOCK)
        return True

    def disconnect(self):
        """Cleans ZMQ comms"""

        if not self._is_connected:
            raise DeviceNotConnectedError(
                "SourcceyClient is not connected. You need to run `robot.connect()` before disconnecting."
            )
        try:
            self._send_base_stop_command()
        except zmq.Again:
            logging.debug("Could not send final base stop before disconnect: socket not ready.")
        except Exception as e:
            logging.debug(f"Could not send final base stop before disconnect: {e}")
        if self.zmq_slam_input_socket is not None:
            close_slam_pub_socket(self.zmq_slam_input_socket)
            self.zmq_slam_input_socket = None
        self.zmq_observation_socket.close()
        self.zmq_cmd_socket.close()
        self.zmq_context.term()
        self._is_connected = False

    ###################################################################
    # Data Management
    ###################################################################
    def get_observation(self) -> dict[str, Any]:
        """
        Capture observations from the remote robot: current follower arm positions,
        present wheel speeds (converted to body-frame velocities: x, y, theta),
        and a camera frame. Receives over ZMQ, translate to body-frame vel
        """
        if not self._is_connected:
            raise DeviceNotConnectedError("SourcceyClient is not connected. You need to run `robot.connect()`.")

        frames, obs_dict, is_fresh = self._get_data()

        # Loop over each configured camera
        for cam_name, frame in frames.items():
            if frame is None:
                logging.warning("Frame is None")
                frame = np.zeros((640, 480, 3), dtype=np.uint8)
            obs_dict[cam_name] = frame

        if is_fresh and self.slam_input_enabled:
            self._publish_slam_input(observation=obs_dict, frames=frames)

        return obs_dict

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Command sourccey to move to a target joint configuration. Translates to motor space + sends over ZMQ

        Args:
            action (np.ndarray): array containing the goal positions for the motors.

        Raises:
            RobotDeviceNotConnectedError: if robot is not connected.

        Returns:
            np.ndarray: the action sent to the motors, potentially clipped.
        """
        if not self._is_connected:
            raise DeviceNotConnectedError(
                "ManipulatorRobot is not connected. You need to run `robot.connect()`."
            )

        # Fill keyboard-owned / optional controls when teleop provides arm-only
        # actions (e.g. bi_sourccey_leader in lerobot-record). Mutate in-place so
        # upstream callers that reuse the dict (dataset logging) see complete keys.
        if "z.pos" not in action and "z.vel" not in action:
            z_hold = self.last_remote_state.get("z.pos", self._z_pos_cmd)
            action["z.pos"] = float(z_hold)
        if "x.vel" not in action:
            action["x.vel"] = 0.0
        if "y.vel" not in action:
            action["y.vel"] = 0.0
        if "theta.vel" not in action:
            action["theta.vel"] = 0.0

        # Convert action to protobuf and send
        robot_action = self.protobuf_converter.action_to_protobuf(action)
        self.zmq_cmd_socket.send(robot_action.SerializeToString())
        self._last_sent_action = dict(action)

        # TODO(Steven): Remove the np conversion when it is possible to record a non-numpy array value
        actions = np.array([action.get(k, 0.0) for k in self._state_order], dtype=np.float32)

        action_sent = {key: actions[i] for i, key in enumerate(self._state_order)}
        action_sent["action"] = actions
        return action_sent

    ###################################################################
    # Private Data Management
    ###################################################################
    def _get_data(self) -> Tuple[Dict[str, np.ndarray], Dict[str, Any], bool]:
        """
        Polls the video socket for the latest observation data.

        Attempts to retrieve and decode the latest message within a short timeout.
        If successful, updates and returns the new frames, speed, and arm state.
        If no new data arrives or decoding fails, returns the last known values.
        """

        # 1. Get the latest message bytes from the socket
        latest_message_bytes = self._poll_and_get_latest_message()
        if latest_message_bytes is None and self.wait_for_fresh_observation:
            deadline = time.monotonic() + max(0.0, self.fresh_observation_timeout_ms) / 1000.0
            while latest_message_bytes is None and time.monotonic() < deadline:
                latest_message_bytes = self._poll_and_get_latest_message()
                if latest_message_bytes is None:
                    time.sleep(0.001)

        # 2. If no message, return cached data
        if latest_message_bytes is None:
            if self.wait_for_fresh_observation:
                raise TimeoutError(
                    "Timed out waiting for a fresh Sourccey observation packet; "
                    "refusing to serve stale camera frames."
                )
            return self.last_frames, self.last_remote_state, False

        # 3. Parse the protobuf message
        try:
            robot_state = sourccey_pb2.SourcceyRobotState()
            robot_state.ParseFromString(latest_message_bytes)
            observation = self.protobuf_converter.protobuf_to_observation(robot_state)
        except Exception as e:
            logging.error(f"Error parsing protobuf observation: {e}")
            return self.last_frames, self.last_remote_state, False

        # 4. If protobuf parsing failed, return cached data
        if observation is None:
            return self.last_frames, self.last_remote_state, False

        # 5. Process the valid observation data
        try:
            new_frames, new_state = self._remote_state_from_obs(observation)
        except Exception as e:
            logging.error(f"Error processing observation data, serving last observation: {e}")
            return self.last_frames, self.last_remote_state, False

        self.last_frames = new_frames
        self.last_remote_state = new_state

        return new_frames, new_state, True

    ###################################################################
    # Private Message and Parsing Functions
    ###################################################################
    def _poll_and_get_latest_message(self) -> Optional[bytes]:
        """Polls the ZMQ socket for a limited time and returns the latest message bytes."""
        poller = zmq.Poller()
        poller.register(self.zmq_observation_socket, zmq.POLLIN)

        try:
            socks = dict(poller.poll(self.polling_timeout_ms))
        except zmq.ZMQError as e:
            logging.error(f"ZMQ polling error: {e}")
            return None

        if self.zmq_observation_socket not in socks:
            if not self.log_no_data_timeouts:
                return None
            now = time.monotonic()
            elapsed = now - self._last_no_data_log_ts
            if elapsed >= self._no_data_log_interval_s:
                if self._suppressed_no_data_logs > 0:
                    logging.info(
                        "No new data available within timeout. (suppressed %d similar messages)",
                        self._suppressed_no_data_logs,
                    )
                    self._suppressed_no_data_logs = 0
                else:
                    logging.info("No new data available within timeout.")
                self._last_no_data_log_ts = now
            else:
                self._suppressed_no_data_logs += 1
            return None

        last_msg = None
        while True:
            try:
                msg = self.zmq_observation_socket.recv(zmq.NOBLOCK)
                last_msg = msg
            except zmq.Again:
                break

        if last_msg is None:
            logging.warning("Poller indicated data, but failed to retrieve message.")

        return last_msg

    def _parse_observation_json(self, obs_string: str) -> Optional[Dict[str, Any]]:
        """Parses the JSON observation string."""
        try:
            return json.loads(obs_string)
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON observation: {e}")
            return None

    def _decode_image_from_b64(self, image_b64: str) -> Optional[np.ndarray]:
        """Decodes a base64 encoded image string to an OpenCV image."""
        if not image_b64:
            return None
        try:
            jpg_data = base64.b64decode(image_b64)
            np_arr = np.frombuffer(jpg_data, dtype=np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                logging.warning("cv2.imdecode returned None for an image.")
            return frame
        except (TypeError, ValueError) as e:
            logging.error(f"Error decoding base64 image data: {e}")
            return None

    def _remote_state_from_obs(
        self, observation: Dict[str, Any]
    ) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
        """Extracts frames, and state from the parsed observation."""
        flat_state = {key: observation.get(key, 0.0) for key in self._state_order}

        state_vec = np.array([flat_state[key] for key in self._state_order], dtype=np.float32)

        obs_dict: Dict[str, Any] = {**flat_state, "observation.state": state_vec}

        # Decode images
        current_frames: Dict[str, np.ndarray] = {}
        for cam_name, image_data in observation.items():
            if cam_name not in self._cameras_ft:
                continue

            # Handle both numpy arrays (from protobuf) and base64 strings (legacy)
            if isinstance(image_data, np.ndarray):
                current_frames[cam_name] = image_data
            elif isinstance(image_data, str):
                frame = self._decode_image_from_b64(image_data)
                if frame is not None:
                    current_frames[cam_name] = frame

        return current_frames, obs_dict

    def _publish_slam_input(self, observation: Dict[str, Any], frames: Dict[str, np.ndarray]) -> None:
        self._slam_input_publisher.publish(
            socket=self.zmq_slam_input_socket,
            observation=observation,
            frames=frames,
        )

    def _build_slam_input_packet(
        self, observation: Dict[str, Any], frames: Dict[str, np.ndarray]
    ) -> Optional[bytes]:
        return self._slam_input_publisher.build_packet(
            observation=observation,
            frames=frames,
        )

    def _log_slam_warning_throttled(self, key: str, message: str) -> None:
        self._slam_input_publisher.log_warning_throttled(key, message)

    ###################################################################
    # Private Control Functions
    ###################################################################
    def _from_keyboard_to_base_action(self, pressed_keys: np.ndarray, z_obs_pos: float | None = None):
        base_sign = 1.0
        z_sign = base_sign
        speed_setting = self.speed_levels[self.speed_index]
        x_speed = speed_setting["x"]
        y_speed = speed_setting["y"]
        z_speed = speed_setting["z"]
        theta_speed = speed_setting["theta"]

        pressed = set(pressed_keys)

        x_cmd = 0.0
        y_cmd = 0.0
        theta_cmd = 0.0
        x_cmd_target = 0.0
        y_cmd_target = 0.0

        if self.teleop_keys["forward"] in pressed:
            x_cmd_target += base_sign * x_speed
        if self.teleop_keys["backward"] in pressed:
            x_cmd_target -= base_sign * x_speed
        if self.teleop_keys["left"] in pressed:
            y_cmd_target += base_sign * y_speed
        if self.teleop_keys["right"] in pressed:
            y_cmd_target -= base_sign * y_speed
        # Z: integrate held keys into a stored position command (z.pos)
        z_dir = 0.0
        if self.teleop_keys["up"] in pressed:
            z_dir += z_sign * z_speed
        if self.teleop_keys["down"] in pressed:
            z_dir -= z_sign * z_speed
        if self.teleop_keys["rotate_left"] in pressed:
            theta_cmd += base_sign * theta_speed
        if self.teleop_keys["rotate_right"] in pressed:
            theta_cmd -= base_sign * theta_speed

        slew_time_s = self._slew_time_s_levels[self.speed_index]
        x_accel = self._x_accel_levels[self.speed_index]
        x_decel = self._x_decel_levels[self.speed_index]
        y_accel = self._y_accel_levels[self.speed_index]
        y_decel = self._y_decel_levels[self.speed_index]

        now = time.monotonic()
        dt = now - self._last_cmd_t
        self._last_cmd_t = now
        dt = max(0.0, min(dt, slew_time_s))  # cap big jumps if the loop stalls

        # Z position target integration should reflect the *actual* loop timing.
        # If we cap dt to 1/30 while the loop runs slower (e.g., due to camera/network load),
        # z.pos changes become tiny and it can take ~seconds before the actuator deadband is exceeded.
        # We already cap dt above with `slew_time_s`, so using dt here is safe and makes Z feel immediate.
        valid_z_obs = (
            z_obs_pos is not None
            and np.isfinite(z_obs_pos)
            and self._z_min <= float(z_obs_pos) <= self._z_max
        )
        if valid_z_obs and not self._z_pos_cmd_initialized:
            self._z_pos_cmd = float(z_obs_pos)
            self._z_pos_cmd_initialized = True

        if z_dir != 0.0:
            requested_step = z_dir * float(self._z_units_per_s) * dt
            z_step = float(np.clip(requested_step, -self._z_max_target_step, self._z_max_target_step))
            self._z_pos_cmd = float(np.clip(self._z_pos_cmd + z_step, self._z_min, self._z_max))
        # With neither key held, freeze the existing target. In particular, do
        # not replace it with a delayed network observation on key release.

        if abs(self._x_cmd_smoothed) >= self._x_deadbane:
            # already moving -> smooth changes
            self._x_cmd_smoothed = self._slew(
                current=self._x_cmd_smoothed,
                target=x_cmd_target,
                dt=dt,
                up_rate=x_accel,
                down_rate=x_decel,
            )
        else:
            # basically stopped -> jump immediately
            self._x_cmd_smoothed = x_cmd_target

        if abs(self._y_cmd_smoothed) >= self._y_deadbane:
            # already moving -> smooth changes
            self._y_cmd_smoothed = self._slew(
                current=self._y_cmd_smoothed,
                target=y_cmd_target,
                dt=dt,
                up_rate=y_accel,
                down_rate=y_decel,
            )
        else:
            # basically stopped -> jump immediately
            self._y_cmd_smoothed = y_cmd_target

        x_cmd = float(self._x_cmd_smoothed)
        y_cmd = float(self._y_cmd_smoothed)
        action = {
            "x.vel": x_cmd,
            "y.vel": y_cmd,
            "theta.vel": theta_cmd,
            "z.pos": self._z_pos_cmd,
        }

        # Integrated keyboard controls: toggle per-arm untorque on key press (edge-triggered)
        try:
            left_key = self.teleop_keys.get("untorque_left")
            right_key = self.teleop_keys.get("untorque_right")

            if left_key and (left_key in pressed) and (left_key not in self._prev_keys):
                self.untorque_left_active = not self.untorque_left_active
            if right_key and (right_key in pressed) and (right_key not in self._prev_keys):
                self.untorque_right_active = not self.untorque_right_active

            # Always include current flags so host can enforce per-arm blocking
            action["untorque_left"] = self.untorque_left_active
            action["untorque_right"] = self.untorque_right_active

            self._prev_keys = pressed
        except Exception:
            pass

        return action

    def _slew(self, current: float, target: float, dt: float, up_rate: float, down_rate: float) -> float:
        delta = target - current
        # If delta would reduce |current| (i.e., braking toward 0), use down_rate, else up_rate.
        rate = down_rate if (current != 0.0 and (current * delta) < 0.0) else up_rate
        max_step = rate * dt
        if delta > max_step:
            return current + max_step
        if delta < -max_step:
            return current - max_step
        return target

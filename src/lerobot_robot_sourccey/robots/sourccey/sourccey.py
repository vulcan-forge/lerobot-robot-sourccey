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

import logging
from functools import cached_property
from typing import Any
import numpy as np
import threading
import time

from lerobot.cameras.utils import make_cameras_from_configs
from lerobot_robot_sourccey.motors.dc_pwm.dc_pwm import PWMDCMotorsController

from lerobot.robots.robot import Robot
from lerobot_robot_sourccey.robots.protobuf.sourccey_protobuf import SourcceyProtobuf
from lerobot_robot_sourccey.robots.sourccey_follower.config_sourccey_follower import SourcceyFollowerConfig
from lerobot_robot_sourccey.robots.sourccey_follower.sourccey_follower import SourcceyFollower
from lerobot_robot_sourccey.robots.sourccey_z_actuator.sourccey_z_actuator import SourcceyZActuator, ZSensor
from .config_sourccey import SourcceyConfig

logger = logging.getLogger(__name__)

class Sourccey(Robot):
    """
    The robot includes a four mecanum wheel mobile base, 1 DC actuator, and 2 remote follower arms.
    The leader arm is connected locally (on the laptop) and its joint positions are recorded and then
    forwarded to the remote follower arm (after applying a safety clamp).
    In parallel, keyboard teleoperation is used to generate raw velocity commands for the wheels.
    """

    config_class = SourcceyConfig
    name = "sourccey"

    def __init__(self, config: SourcceyConfig):
        super().__init__(config)
        self.config = config

        left_arm_config = SourcceyFollowerConfig(
            id=f"{config.id}_left" if config.id else None,
            calibration_dir=config.calibration_dir,
            motor_models=config.left_arm_motor_models,
            port=config.left_arm_port,
            disable_torque_on_disconnect=config.left_arm_disable_torque_on_disconnect,
            max_relative_target=config.left_arm_max_relative_target,
            use_degrees=config.left_arm_use_degrees,
            cameras={},
        )
        right_arm_config = SourcceyFollowerConfig(
            id=f"{config.id}_right" if config.id else None,
            calibration_dir=config.calibration_dir,
            motor_models=config.right_arm_motor_models,
            port=config.right_arm_port,
            orientation="right",
            disable_torque_on_disconnect=config.right_arm_disable_torque_on_disconnect,
            max_relative_target=config.right_arm_max_relative_target,
            use_degrees=config.right_arm_use_degrees,
            cameras={},
        )

        self.left_arm = SourcceyFollower(left_arm_config)
        self.right_arm = SourcceyFollower(right_arm_config)
        self.cameras = make_cameras_from_configs(config.cameras)
        # Cameras are treated as best-effort: startup should not fail if a camera fails to connect/read.
        self._connected_cameras: set[str] = set()

        self.dc_motors_controller = PWMDCMotorsController(
            motors=self.config.dc_motors,
            config=self.config.dc_motors_config,
        )

         # Z Actuator Code
        self.z_sensor = ZSensor(adc_channel=1, vref=3.30, average_samples=max(1, config.z_adc_samples))
        self.z_actuator = SourcceyZActuator(
            sensor=self.z_sensor,
            driver=self.dc_motors_controller,
            motor="linear_actuator",
            proportional_gain=config.z_proportional_gain,
            minimum_up_command=config.z_minimum_up_command,
            minimum_down_command=config.z_minimum_down_command,
            maximum_command=config.z_maximum_command,
            position_deadband=config.z_position_deadband,
            control_hz=config.z_control_hz,
        )

        # Initialize protobuf converter
        self.protobuf_converter = SourcceyProtobuf()

        # Track per-arm untorque state for edge detection
        self.untorque_left_prev = False
        self.untorque_right_prev = False
        self._z_hardware_available = True
        # This is replaced with a real sensor reading during connect.  Zero is a
        # neutral fallback; using +100 here could issue an unintended full-up
        # command when the first ADC read was temporarily unavailable.
        self._last_known_z_pos = 0.0
        self._z_command_target = 0.0
        self._last_z_velocity_command_t = time.monotonic()

    def __del__(self):
        # Destructors can run on partially initialized objects if __init__ raised.
        try:
            if hasattr(self, "left_arm") and hasattr(self, "right_arm") and self.is_connected:
                self.disconnect()
        except Exception:
            pass

    ###################################################################
    # Properties and Attributes
    ###################################################################
    @property
    def _state_ft(self) -> dict[str, type]:
        return {
            f"left_{motor}.pos": float for motor in self.left_arm.bus.motors} | {
            f"right_{motor}.pos": float for motor in self.right_arm.bus.motors} | {
                "z.pos": float,
                "x.vel": float,
                "y.vel": float,
                "theta.vel": float,
                "z.vel": float,
            }

    @property
    def _cameras_ft(self) -> dict[str, tuple]:
        return {
            cam: (self.config.cameras[cam].height, self.config.cameras[cam].width, 3) for cam in self.cameras
        }

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

    @property
    def is_connected(self) -> bool:
        left_arm_connected = self.left_arm is not None and self.left_arm.is_connected
        right_arm_connected = self.right_arm is not None and self.right_arm.is_connected
        arms_connected = left_arm_connected and right_arm_connected

        # Only require cameras that successfully connected (failed cameras are ignored).
        cams_connected = all(self.cameras[k].is_connected for k in self._connected_cameras)
        return arms_connected and cams_connected

    ###################################################################
    # Connection Management
    ###################################################################
    def connect(self, calibrate: bool = True) -> None:
        self.left_arm.connect(calibrate)
        self.right_arm.connect(calibrate)

        self._z_hardware_available = True
        try:
            self.dc_motors_controller.connect()
            self.z_actuator.connect()
            try:
                self._last_known_z_pos = float(self.z_actuator.read_position())
                self._z_command_target = self._last_known_z_pos
            except Exception as exc:
                logger.warning("Could not initialize Z position from the sensor: %s", exc)
        except RuntimeError as exc:
            self._z_hardware_available = False
            self.z_actuator.use_z_actuator = False
            logger.warning(
                "Skipping base/Z hardware during connect: %s. Continuing without Z calibration/control.",
                exc,
            )

        # Connect only target cameras
        self._connected_cameras.clear()
        for cam_key in self.cameras.keys():
            try:
                self.cameras[cam_key].connect()
                self._connected_cameras.add(cam_key)
            except Exception as e:
                logger.warning(f"Camera '{cam_key}' failed to connect: {e}. Continuing without it.")

    def disconnect(self):
        if not self.is_connected:
            return

        logger.info(f"Disconnecting Sourccey")
        self.left_arm.disconnect()
        self.right_arm.disconnect()

        self.stop_base()
        self.dc_motors_controller.disconnect()

        self.z_actuator.stop()
        self.z_actuator.disconnect()

        # Disconnect only those we connected
        for cam_key in list(self._connected_cameras):
            try:
                self.cameras[cam_key].disconnect()
            except Exception:
                pass
        self._connected_cameras.clear()

        logger.info(f"Sourccey disconnected.")

    ###################################################################
    # Calibration and Configuration Management
    ###################################################################
    @property
    def is_calibrated(self) -> bool:
        return self.left_arm.is_calibrated and self.right_arm.is_calibrated

    def calibrate(self) -> None:
        self.left_arm.calibrate()
        self.right_arm.calibrate()

    def auto_calibrate(self, full_reset: bool = False, arm: str | None = None) -> None:
        """
        Auto-calibrate robot joints.

        If arm is None, calibrate Z first, then start left arm immediately and
        right arm 3 seconds later.
        arm can be "left" or "right" to calibrate only that side.
        """
        if arm is None:
            if full_reset:
                self.disable_arm_torque()

            # Soft robot calibration should not physically move the Z actuator.
            # Only a full reset re-detects Z limits by movement.
            z_calibration_result = None
            if self._z_hardware_available:
                z_calibration_result = self.z_actuator.calibrator.auto_calibrate(full_reset=full_reset)
                if z_calibration_result is not None:
                    logger.info(
                        "Z auto-calibration saved successfully: raw_min=%s raw_max=%s invert=%s",
                        z_calibration_result.raw_min,
                        z_calibration_result.raw_max,
                        z_calibration_result.invert,
                    )
            else:
                logger.warning(
                    "Skipping Z auto-calibration because GPIO/Z hardware is unavailable on this machine."
                )

            calibration_errors: list[tuple[str, BaseException]] = []

            def run_arm_calibration(arm_name: str, arm_obj, **kwargs) -> None:
                try:
                    arm_obj.auto_calibrate(**kwargs)
                except BaseException as exc:
                    logger.exception("Auto-calibration failed for %s arm", arm_name)
                    calibration_errors.append((arm_name, exc))

            # Create threads for each arm
            left_thread = threading.Thread(
                target=run_arm_calibration,
                args=("left", self.left_arm),
                kwargs={"reverse": False, "full_reset": full_reset},
            )
            right_thread = threading.Thread(
                target=run_arm_calibration,
                args=("right", self.right_arm),
                kwargs={"reverse": True, "full_reset": full_reset},
            )

            # Start left arm immediately
            left_thread.start()

            # Wait 3 seconds before starting right arm
            time.sleep(3)
            right_thread.start()

            # Wait for both threads to complete
            left_thread.join()
            right_thread.join()

            if calibration_errors:
                error_messages = ", ".join(f"{arm_name}: {exc}" for arm_name, exc in calibration_errors)
                message = f"Arm auto-calibration failed ({error_messages})"
                if z_calibration_result is not None:
                    message += ". Z calibration was saved successfully."
                raise RuntimeError(message) from calibration_errors[0][1]

        elif arm == "left":
            self.left_arm.auto_calibrate(reverse=False, full_reset=full_reset)
        elif arm == "right":
            self.right_arm.auto_calibrate(reverse=True, full_reset=full_reset)
        else:
            raise ValueError("arm must be one of: None, 'left', 'right'")

        print("Auto-calibration completed")
        return True

    def configure(self) -> None:
        self.left_arm.configure()
        self.right_arm.configure()

    def setup_motors(self) -> None:
        self.left_arm.setup_motors()
        self.right_arm.setup_motors()

    ###################################################################
    # Data Management
    ###################################################################

    def get_observation(self) -> dict[str, Any]:
        try:
            start = time.perf_counter()

            obs_dict = {}

            left_obs = self.left_arm.get_observation()
            obs_dict.update({f"left_{key}": value for key, value in left_obs.items()})

            right_obs = self.right_arm.get_observation()
            obs_dict.update({f"right_{key}": value for key, value in right_obs.items()})

            base_wheel_vel = self.dc_motors_controller.get_velocities()
            base_vel = self._wheel_normalized_to_body(base_wheel_vel)
            obs_dict.update(base_vel)

            # Z actuator position (best-effort; keep schema stable).
            # Reuse the last good reading on transient ADC/SPI failures instead of
            # snapping back to +100, which can look like live recalibration drift.
            if self.z_actuator is not None and self.z_actuator.is_connected and self.z_actuator.use_z_actuator:
                try:
                    self._last_known_z_pos = float(self.z_actuator.read_position())
                except Exception as exc:
                    logger.warning("Failed to read z actuator position; reusing last good value: %s", exc)
            obs_dict["z.pos"] = float(self._last_known_z_pos)
            obs_dict["z.vel"] = 0.0

            for cam_key in self.cameras.keys():
                try:
                    start = time.perf_counter()
                    obs_dict[cam_key] = self.cameras[cam_key].read_latest()
                    dt_ms = (time.perf_counter() - start) * 1e3
                    logger.debug(f"{self} read {cam_key}: {dt_ms:.1f}ms")
                except Exception as e:
                    # Keep the observation schema stable even if a camera is down.
                    h = int(self.config.cameras[cam_key].height)
                    w = int(self.config.cameras[cam_key].width)
                    obs_dict[cam_key] = np.zeros((h, w, 3), dtype=np.uint8)
                    logger.warning(f"Camera '{cam_key}' read failed: {e}. Using black frame.")

            dt_ms = (time.perf_counter() - start) * 1e3
            logger.debug(f"{self} get_observation took: {dt_ms:.1f}ms")

            return obs_dict
        except Exception as e:
            print(f"Error getting observation: {e}")
            return {}

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        try:
            # Apply per-arm untorque flags automatically
            action = self.apply_untorque_flags(action)

            left_action = {key.removeprefix("left_"): value for key, value in action.items() if key.startswith("left_")}
            right_action = {key.removeprefix("right_"): value for key, value in action.items() if key.startswith("right_")}
            base_goal_vel = {k: v for k, v in action.items() if k.endswith(".vel")}
            base_goal_pos = {k: v for k, v in action.items() if k.endswith(".pos")}

            prefixed_send_action_left = {}
            prefixed_send_action_right = {}

            # Only send to followers if there are keys for that arm
            if left_action:
                sent_left = self.left_arm.send_action(left_action)
            else:
                sent_left = {}
            if right_action:
                sent_right = self.right_arm.send_action(right_action)
            else:
                sent_right = {}

            prefixed_send_action_left = {f"left_{key}": value for key, value in sent_left.items()}
            prefixed_send_action_right = {f"right_{key}": value for key, value in sent_right.items()}

            # Base velocity
            wheel_action = self._body_to_wheel_normalized(
                base_goal_vel.get("x.vel", 0.0),
                base_goal_vel.get("y.vel", 0.0),
                base_goal_vel.get("theta.vel", 0.0)
            )

            # Z accepts either an absolute position or a normalized velocity.
            if "z.pos" in base_goal_pos and self.z_actuator.use_z_actuator:
                try:
                    self._z_command_target = float(np.clip(base_goal_pos["z.pos"], -100.0, 100.0))
                    self.z_actuator.move_to_position(self._z_command_target, instant=True)
                except Exception as e:
                    logger.warning(f"Failed to command z actuator: {e}")
            elif "z.vel" in base_goal_vel and self.z_actuator.use_z_actuator:
                try:
                    now = time.monotonic()
                    dt = max(0.0, min(now - self._last_z_velocity_command_t, 0.1))
                    self._last_z_velocity_command_t = now
                    z_velocity = float(np.clip(base_goal_vel["z.vel"], -1.0, 1.0))
                    self._z_command_target = float(
                        np.clip(
                            self._z_command_target + z_velocity * self.config.z_velocity_units_per_s * dt,
                            -100.0,
                            100.0,
                        )
                    )
                    self.z_actuator.move_to_position(self._z_command_target, instant=True)
                except Exception as e:
                    logger.warning(f"Failed to apply Z velocity command: {e}")

            dc_motors_action = {**wheel_action }
            self.dc_motors_controller.set_velocities(dc_motors_action)

            sent_action = {**prefixed_send_action_left, **prefixed_send_action_right, **base_goal_pos, **base_goal_vel}
            return sent_action
        except Exception as e:
            print(f"Error sending action: {e}")
            return {}

    ###################################################################
    # Control Management
    ###################################################################
    def apply_untorque_flags(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        Apply per-arm untorque flags: disable/enable torque and strip positions.
        Manages internal state for edge detection.

        Returns:
            dict: modified action with positions stripped if untorqued
        """
        left_flag = bool(action.get("untorque_left", False))
        right_flag = bool(action.get("untorque_right", False))

        # Left arm handling
        if left_flag:
            if not self.untorque_left_prev:
                self.left_arm.bus.disable_torque()
            action = {k: v for k, v in action.items() if not k.startswith("left_")}
        elif self.untorque_left_prev and not left_flag:
            self.left_arm.bus.enable_torque()

        # Right arm handling
        if right_flag:
            if not self.untorque_right_prev:
                self.right_arm.bus.disable_torque()
            action = {k: v for k, v in action.items() if not k.startswith("right_")}
        elif self.untorque_right_prev and not right_flag:
            self.right_arm.bus.enable_torque()

        # Update state
        self.untorque_left_prev = left_flag
        self.untorque_right_prev = right_flag

        return action

    def update(self):
        # Can be used to update the robot every cycle. Such as potentially a motor
        self.dc_motors_controller.update_velocity(max_step=0.25)

    # Base Functions
    def stop_base(self):
        self.dc_motors_controller.set_velocities({"front_left": 0, "front_right": 0, "rear_left": 0, "rear_right": 0})

    def disable_arm_torque(self) -> None:
        """
        Disable torque on both follower arms so they can be freely moved by hand.

        Also marks internal untorque edge state as active so the next streamed command
        with untorque flags set to `False` will cleanly re-enable torque.
        """
        for arm_name, arm in (("left", self.left_arm), ("right", self.right_arm)):
            try:
                arm.bus.disable_torque()
            except Exception as e:
                logger.warning(f"Failed to disable torque on {arm_name} arm: {e}")

        self.untorque_left_prev = True
        self.untorque_right_prev = True

    def watchdog_stop_and_relax(self) -> None:
        """
        Host watchdog fail-safe: stop mobile + z motion and fully release arm torque.
        This is unused at the moment as we wont want the robot relaxing while its supposed to be active
        """
        self.stop_base()
        try:
            self.z_actuator.stop()
        except Exception as e:
            logger.warning(f"Failed to stop z actuator during watchdog: {e}")
        self.disable_arm_torque()

    ##################################################################################
    # Private Kinematic Functions
    ##################################################################################
    def _body_to_wheel_normalized(
        self,
        x: float,
        y: float,
        theta: float,
    ) -> dict:
        velocity_vector = np.array([x, y, theta], dtype=float)

        # Build the correct kinematic matrix for mecanum wheels
        # Columns correspond to [x, y (strafe), theta (turn)].
        # This mapping makes A/D (y.vel) strafe and Z/X (theta.vel) rotate.
        m = np.array([
            [ 1, -1,  1], # Front-left wheel
            [-1, -1,  1], # Front-right wheel
            [ 1,  1,  1], # Rear-left wheel
            [-1,  1,  1], # Rear-right wheel
        ])

        wheel_normalized = m.dot(velocity_vector)
        wheel_normalized = np.clip(wheel_normalized, -1.0, 1.0)
        wheel_dict = {
            "front_left": float(wheel_normalized[0]),
            "front_right": float(wheel_normalized[1]),
            "rear_left": float(wheel_normalized[2]),
            "rear_right": float(wheel_normalized[3]),
        }

        return wheel_dict

    def _wheel_normalized_to_body(
        self,
        wheel_normalized: dict[str, Any],
    ) -> dict[str, Any]:

        # Convert each normalized command back to an angular speed in deg/s.
        wheel_array = np.array([
            wheel_normalized["front_left"],
            wheel_normalized["front_right"],
            wheel_normalized["rear_left"],
            wheel_normalized["rear_right"],
        ])

        # Kinematic matrix for mecanum wheels (must match forward kinematics)
        m = np.array([
            [ 1, -1,  1], # Front-left wheel
            [-1, -1,  1], # Front-right wheel
            [ 1,  1,  1], # Rear-left wheel
            [-1,  1,  1], # Rear-right wheel
        ])

        # Solve the inverse kinematics: body_velocity = M⁺ · wheel_linear_speeds.
        m_pinv = np.linalg.pinv(m)
        velocity_vector = m_pinv.dot(wheel_array)
        x, y, theta = velocity_vector

        return {
            "x.vel": self.clean_value(x),
            "y.vel": self.clean_value(y),
            "theta.vel": self.clean_value(theta),
        }

    # Round to prevent floating-point precision issues and handle -0.0
    def clean_value(self, val):
        rounded = round(val, 8)

        # Convert -0.0 to 0.0 and very small values to 0.0
        return 0.0 if abs(rounded) < 1e-10 else rounded

    ##################################################################################
    # Motor Configuration Functions
    ##################################################################################
    def set_baud_rate(self, baud_rate: int) -> None:
        self.left_arm.bus.set_baudrate(baud_rate)
        self.right_arm.bus.set_baudrate(baud_rate)

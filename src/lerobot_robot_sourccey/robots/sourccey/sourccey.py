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
from lerobot_robot_sourccey.calibration import CalibrationRecoveryMixin
from lerobot_robot_sourccey.policy_observations import MissingArmObservations
import threading
import time
from collections.abc import Callable
from functools import cached_property
from typing import Any, TypeVar, overload

import numpy as np

from lerobot.cameras.utils import make_cameras_from_configs
from lerobot_robot_sourccey.motors.dc_pwm.dc_pwm import PWMDCMotorsController

from lerobot.robots.robot import Robot
from lerobot_robot_sourccey.robots.protobuf.sourccey_protobuf import SourcceyProtobuf
from lerobot_robot_sourccey.robots.sourccey_follower.config_sourccey_follower import SourcceyFollowerConfig
from lerobot_robot_sourccey.robots.sourccey_follower.sourccey_follower import SourcceyFollower
from lerobot_robot_sourccey.robots.sourccey_z_actuator.sourccey_z_actuator import SourcceyZActuator, ZSensor
from .config_sourccey import SourcceyConfig

logger = logging.getLogger(__name__)
T = TypeVar("T")


@overload
def _try_hardware(operation: str, callback: Callable[[], T], fallback: T) -> T: ...


@overload
def _try_hardware(operation: str, callback: Callable[[], T]) -> T | None: ...


def _try_hardware(operation: str, callback: Callable[[], T], fallback: T | None = None) -> T | None:
    """Log an isolated hardware failure and return the caller's fallback.

    Use only for best-effort operations. Startup and calibration retain their
    own exception policies so unexpected failures still propagate.
    """
    try:
        return callback()
    except Exception as exc:
        logger.warning("%s failed: %s", operation, exc)
        return fallback


class Sourccey(CalibrationRecoveryMixin, Robot):
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
        self._policy_observations = MissingArmObservations(config.missing_arm_positions)

        left_arm_config = SourcceyFollowerConfig(
            id=f"{config.id}_left" if config.id else None,
            calibration_dir=config.calibration_dir,
            motor_models=config.left_arm_motor_models,
            motor_retries=config.motor_retries,
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
            motor_retries=config.motor_retries,
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
        self._connected = False

        self.dc_motors_controller = PWMDCMotorsController(
            motors=self.config.dc_motors,
            config=self.config.dc_motors_config,
        )

        # Base and lift share the same motor controller.
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
        self._last_base_goal_vel = {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}

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
        return self._connected

    @property
    def available_arms(self) -> dict[str, bool]:
        """Live availability of each follower arm, independent of robot startup."""
        return {
            name: arm.is_connected
            for name, arm in self._followers()
        }

    def _followers(self) -> tuple[tuple[str, SourcceyFollower], ...]:
        return (("left", self.left_arm), ("right", self.right_arm))

    def _available_followers(self) -> list[tuple[str, SourcceyFollower]]:
        return [
            (name, arm)
            for name, arm in self._followers()
            if arm.is_connected
        ]

    ###################################################################
    # Connection Management
    ###################################################################
    def connect(self, calibrate: bool = True) -> None:
        if self._connected:
            return
        self._connect_arms(calibrate)
        self._connect_base_and_lift()
        self._connect_cameras()
        self._connected = True

    def _connect_arms(self, calibrate: bool) -> None:
        for name, arm in self._followers():
            try:
                arm.connect(calibrate)
            except (ConnectionError, OSError) as exc:
                # A failed handshake can leave the serial port open.
                if arm.bus.is_connected:
                    _try_hardware(f"Clean up {name} arm", arm.bus.disconnect)
                if not self.config.allow_partial_connection:
                    self.disconnect()
                    raise
                logger.warning("%s arm unavailable: %s. Continuing without it.", name, exc)

    def _connect_base_and_lift(self) -> None:
        self._z_hardware_available = True
        try:
            self.dc_motors_controller.connect()
            self.z_actuator.connect()
            self._last_known_z_pos = _try_hardware(
                "Initialize Z position", self._read_z_sensor, self._last_known_z_pos
            )
            self._z_command_target = self._last_known_z_pos
        except RuntimeError as exc:
            self._z_hardware_available = False
            self.z_actuator.use_z_actuator = False
            logger.warning(
                "Skipping base/Z hardware during connect: %s. Continuing without Z calibration/control.",
                exc,
            )

    def _connect_cameras(self) -> None:
        self._connected_cameras.clear()
        for cam_key in self.cameras.keys():
            def connect_camera() -> bool:
                self.cameras[cam_key].connect()
                return True

            if _try_hardware(f"Connect camera '{cam_key}'", connect_camera, False):
                self._connected_cameras.add(cam_key)

    def disconnect(self) -> None:
        self._connected = False

        logger.info("Disconnecting Sourccey")
        for name, arm in self._available_followers():
            _try_hardware(f"Disconnect {name} arm", arm.disconnect)

        for operation, cleanup in (
            ("Stop base", self.stop_base),
            ("Stop lift", self.z_actuator.stop),
            ("Disconnect lift", self.z_actuator.disconnect),
            ("Disconnect base controller", self.dc_motors_controller.disconnect),
        ):
            _try_hardware(operation, cleanup)

        # Disconnect only those we connected
        for cam_key in list(self._connected_cameras):
            _try_hardware(f"Disconnect camera '{cam_key}'", self.cameras[cam_key].disconnect)
        self._connected_cameras.clear()

        logger.info("Sourccey disconnected.")

    ###################################################################
    # Calibration and Configuration Management
    ###################################################################
    @property
    def is_calibrated(self) -> bool:
        return all(arm.is_calibrated for _, arm in self._available_followers())

    def calibrate(self) -> None:
        for _, arm in self._available_followers():
            arm.calibrate()

    def auto_calibrate(self, full_reset: bool = False, arm: str | None = None) -> None:
        """
        Auto-calibrate robot joints.

        If arm is None, calibrate Z first, then available arms with a 3-second
        delay between starts.
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

            threads = []
            for name, follower in self._available_followers():
                if threads:
                    time.sleep(3)
                thread = threading.Thread(
                    target=run_arm_calibration,
                    args=(name, follower),
                    kwargs={"reverse": name == "right", "full_reset": full_reset},
                )
                thread.start()
                threads.append(thread)
            for thread in threads:
                thread.join()

            if calibration_errors:
                error_messages = ", ".join(f"{arm_name}: {exc}" for arm_name, exc in calibration_errors)
                message = f"Arm auto-calibration failed ({error_messages})"
                if z_calibration_result is not None:
                    message += ". Z calibration was saved successfully."
                raise RuntimeError(message) from calibration_errors[0][1]

        elif arm == "left":
            if not self.left_arm.is_connected:
                raise ConnectionError("Left arm is unavailable")
            self.left_arm.auto_calibrate(reverse=False, full_reset=full_reset)
        elif arm == "right":
            if not self.right_arm.is_connected:
                raise ConnectionError("Right arm is unavailable")
            self.right_arm.auto_calibrate(reverse=True, full_reset=full_reset)
        else:
            raise ValueError("arm must be one of: None, 'left', 'right'")

        print("Auto-calibration completed")
        return True

    def configure(self) -> None:
        for _, arm in self._available_followers():
            arm.configure()

    def setup_motors(self) -> None:
        for _, arm in self._available_followers():
            arm.setup_motors()

    ###################################################################
    # Data Management
    ###################################################################

    def get_observation(self) -> dict[str, Any]:
        observation = _try_hardware("Get observation", self._read_observation, {})
        if self.config.missing_arm_positions:
            observation = self._policy_observations.observation(observation)
        return observation

    def _read_observation(self) -> dict[str, Any]:
        start = time.perf_counter()
        observation = {}
        for name, arm in self._followers():
            observation.update(self._read_arm(name, arm))

        wheel_velocities = self.dc_motors_controller.get_velocities()
        observation.update(self._wheel_normalized_to_body(wheel_velocities))
        observation["z.pos"] = self._read_z_position()
        for name in self.cameras:
            observation[name] = self._read_camera(name)

        logger.debug("%s get_observation took: %.1fms", self, (time.perf_counter() - start) * 1e3)
        return observation

    def _read_arm(self, name: str, arm: SourcceyFollower) -> dict[str, Any]:
        positions = {f"{motor}.pos": float("nan") for motor in arm.bus.motors}
        if arm.is_connected:
            positions.update(_try_hardware(f"Read {name} arm", arm.get_observation, {}))
        return {f"{name}_{key}": value for key, value in positions.items()}

    def _read_z_sensor(self) -> float:
        return float(self.z_actuator.read_position())

    def _read_z_position(self) -> float:
        # Keep the last good reading on transient ADC/SPI failures.
        if self.z_actuator is not None and self.z_actuator.is_connected and self.z_actuator.use_z_actuator:
            self._last_known_z_pos = _try_hardware(
                "Read Z position; retaining last good value", self._read_z_sensor, self._last_known_z_pos
            )
        return float(self._last_known_z_pos)

    def _read_camera(self, name: str) -> np.ndarray:
        def read_frame():
            camera = self.cameras[name]
            read_latest = getattr(camera, "read_latest", None)
            if callable(read_latest):
                return read_latest()
            # Stock LeRobot cameras expose async_read instead of read_latest.
            # Bound the wait so a failed camera cannot stall the handshake.
            return camera.async_read(timeout_ms=50)

        frame = _try_hardware(f"Read camera '{name}'", read_frame)
        if frame is not None:
            return frame
        config = self.config.cameras[name]
        return np.zeros((int(config.height), int(config.width), 3), dtype=np.uint8)

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        return _try_hardware("Send action", lambda: self._send_action(action), {})

    def _send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        action = self.apply_untorque_flags(action)
        sent = {}
        for name, arm in self._available_followers():
            sent.update(self._send_arm_action(name, arm, action))

        base_velocity = {key: value for key, value in action.items() if key.endswith(".vel")}
        # Preserve command ordering: lift target precedes wheel output.
        wheel_action = self._prepare_base_action(base_velocity)
        if "z.pos" in action and self.z_actuator.use_z_actuator:
            _try_hardware("Command lift", lambda: self._send_z_target(action["z.pos"]))
        if wheel_action is not None:
            self.dc_motors_controller.set_velocities(wheel_action)

        if "z.pos" in action:
            sent["z.pos"] = action["z.pos"]
        sent.update(base_velocity)
        return sent

    def _send_arm_action(self, name: str, arm: SourcceyFollower, action: dict[str, Any]) -> dict[str, Any]:
        prefix = f"{name}_"
        targets = {key.removeprefix(prefix): value for key, value in action.items() if key.startswith(prefix)}
        if not targets:
            return {}
        sent = _try_hardware(f"Command {name} arm", lambda: arm.send_action(targets), {})
        return {f"{prefix}{key}": value for key, value in sent.items()}

    def _prepare_base_action(self, velocity: dict[str, float]) -> dict[str, float] | None:
        # Missing axes retain their targets; arm-only commands leave the base alone.
        if not velocity:
            return None
        self._last_base_goal_vel.update(velocity)
        return self._body_to_wheel_normalized(
            self._last_base_goal_vel["x.vel"],
            self._last_base_goal_vel["y.vel"],
            self._last_base_goal_vel["theta.vel"],
        )

    def _send_z_target(self, target: float) -> None:
        self._z_command_target = float(np.clip(target, -100.0, 100.0))
        self.z_actuator.move_to_position(self._z_command_target, instant=True)

    ###################################################################
    # Control Management
    ###################################################################
    def _set_arm_torque(self, arm: SourcceyFollower, enabled: bool) -> None:
        operation = arm.bus.enable_torque if enabled else arm.bus.disable_torque
        _try_hardware("Change arm torque", operation)

    def apply_untorque_flags(self, action: dict[str, Any]) -> dict[str, Any]:
        """Apply torque transitions and remove targets for relaxed arms."""
        for name, arm in self._followers():
            flag_key = f"untorque_{name}"
            previous_key = f"untorque_{name}_prev"
            previous = getattr(self, previous_key)
            relaxed = bool(action.get(flag_key, previous))
            if relaxed != previous and arm.is_connected:
                self._set_arm_torque(arm, enabled=not relaxed)
            if relaxed:
                action = {key: value for key, value in action.items() if not key.startswith(f"{name}_")}
            setattr(self, previous_key, relaxed)
        return action

    def update(self):
        # Can be used to update the robot every cycle. Such as potentially a motor
        self.dc_motors_controller.update_velocity(max_step=0.25)

    # Base Functions
    def stop_base(self):
        self.dc_motors_controller.set_velocities({"front_left": 0, "front_right": 0, "rear_left": 0, "rear_right": 0})
        self._last_base_goal_vel = {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}

    def disable_arm_torque(self) -> None:
        """
        Disable torque on both follower arms so they can be freely moved by hand.

        Also marks internal untorque edge state as active so the next streamed command
        with untorque flags set to `False` will cleanly re-enable torque.
        """
        for _, arm in self._available_followers():
            self._set_arm_torque(arm, enabled=False)

        self.untorque_left_prev = True
        self.untorque_right_prev = True

    def watchdog_stop_and_relax(self) -> None:
        """
        Host watchdog fail-safe: stop mobile + z motion and fully release arm torque.
        This is unused at the moment as we wont want the robot relaxing while its supposed to be active
        """
        self.stop_base()
        _try_hardware("Stop lift during watchdog", self.z_actuator.stop)
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

        # Columns correspond to [x, y (strafe), theta (turn)]. The X/Y
        # polarities match Sourccey's installed motor wiring: positive X moves
        # forward and positive Y strafes left. Rotation uses the existing
        # positive-left convention.
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
        for _, arm in self._available_followers():
            arm.bus.set_baudrate(baud_rate)

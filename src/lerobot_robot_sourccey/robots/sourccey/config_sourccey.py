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

from dataclasses import dataclass, field, fields

from lerobot.cameras.configs import CameraConfig
from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot_robot_sourccey.motors.dc_motors_controller import DCMotor, MotorNormMode

from lerobot.robots.config import RobotConfig
from .modules.slam.config import SlamInputConfig


def _opencv_camera(index_or_path: str) -> OpenCVCameraConfig:
    """Create a camera config on both stock LeRobot and the Vulcan camera fork."""
    values = {
        "index_or_path": index_or_path,
        "fps": 30,
        "width": 320,
        "height": 240,
    }
    reconnect_values = {
        "auto_reconnect": True,
        "max_consecutive_read_failures": 2,
        "fast_reconnect_interval_s": 0.05,
        "fast_reconnect_window_s": 2.0,
        "reconnect_interval_s": 0.5,
    }
    supported = {item.name for item in fields(OpenCVCameraConfig)}
    values.update({key: value for key, value in reconnect_values.items() if key in supported})
    return OpenCVCameraConfig(**values)


def sourccey_cameras_config() -> dict[str, CameraConfig]:
    return {
        "front_left": _opencv_camera("/dev/cameraFrontLeft"),
        "front_right": _opencv_camera("/dev/cameraFrontRight"),
        "wrist_left": _opencv_camera("/dev/cameraWristLeft"),
        "wrist_right": _opencv_camera("/dev/cameraWristRight"),
    }

def sourccey_motor_models() -> dict[str, str]:
    return {
        "shoulder_pan": "sts3215",
        "shoulder_lift": "sts3250",
        "elbow_flex": "sts3250",
        "wrist_flex": "sts3215",
        "wrist_roll": "sts3215",
        "gripper": "sts3215",
    }

def sourccey_dc_motors() -> dict[str, DCMotor]:
    return {
        "front_left": DCMotor(id=1, model="mecanum_wheel", norm_mode=MotorNormMode.PWM_DUTY_CYCLE),
        "front_right": DCMotor(id=2, model="mecanum_wheel", norm_mode=MotorNormMode.PWM_DUTY_CYCLE),
        "rear_left": DCMotor(id=3, model="mecanum_wheel", norm_mode=MotorNormMode.PWM_DUTY_CYCLE),
        "rear_right": DCMotor(id=4, model="mecanum_wheel", norm_mode=MotorNormMode.PWM_DUTY_CYCLE),
        "linear_actuator": DCMotor(id=5, model="linear_actuator", norm_mode=MotorNormMode.PWM_DUTY_CYCLE),
    }

def sourccey_dc_motors_config() -> dict:
    return {
        "in1_pins": [17,23,24,26,5], # Physical pins: [11, 16, 18, 37, 29]
        "in2_pins": [27,22,25,16,6], # Physical pins: [13, 15, 22, 36, 31]
        "pwm_frequency": 10000,  # 5 kHz - balance between performance and noise reduction
    }

@RobotConfig.register_subclass("sourccey")
@dataclass
class SourcceyConfig(RobotConfig):
    left_arm_port: str = "/dev/robotLeftArm"
    right_arm_port: str = "/dev/robotRightArm"

    left_arm_motor_models: dict[str, str] = field(default_factory=sourccey_motor_models)
    right_arm_motor_models: dict[str, str] = field(default_factory=sourccey_motor_models)

    cameras: dict[str, CameraConfig] = field(default_factory=sourccey_cameras_config)

    dc_motors_config: dict = field(default_factory=sourccey_dc_motors_config)
    dc_motors: dict = field(default_factory=sourccey_dc_motors)

    # Z actuator runtime control. Calibration remains stored separately.
    z_adc_samples: int = 10
    z_proportional_gain: float = 0.035
    z_minimum_up_command: float = 0.82
    z_minimum_down_command: float = 0.82
    z_maximum_command: float = 1.0
    z_position_deadband: float = 0.75
    z_control_hz: float = 50.0
    z_velocity_units_per_s: float = 25.0

    # Optional
    left_arm_disable_torque_on_disconnect: bool = True
    left_arm_max_relative_target: int | None = None
    left_arm_use_degrees: bool = False
    right_arm_disable_torque_on_disconnect: bool = True
    right_arm_max_relative_target: int | None = None
    right_arm_use_degrees: bool = False


@dataclass
class SourcceyHostConfig:
    # Network Configuration
    port_zmq_cmd: int = 5555
    port_zmq_observations: int = 5556

    # Text + audio (used by voice pipeline)
    port_zmq_text_in: int = 5557  # receive text from client
    port_zmq_text_out: int = 5558  # send text/events to client
    port_zmq_audio: int = 5559  # publish PCM16 audio stream

    # Discovery Ports
    discovery_port: int = 42111

    # Duration of the application
    connection_time_s: int = 86400

    # Dead-man watchdog: stale command streams stop only the mobile base.
    watchdog_timeout_ms: int = 500

    # If robot jitters decrease the frequency and monitor cpu load with `top` in cmd
    max_loop_freq_hz: int = 30

    # Websocket relay controls.
    websocket_relay_autostart: bool = True
    # Start command-only by default; set True to uplink observations too.
    websocket_relay_forward_observations: bool = True

    # IMU periodic logging on host (disabled by default to avoid loop spam)
    imu_print_enabled: bool = False
    imu_print_interval_s: float = 10.0
    imu_bus_num: int = 1
    imu_lsm6dsox_address: int = 0x6A
    imu_lis3mdl_address: int = 0x1C


@RobotConfig.register_subclass("sourccey_client")
@dataclass
class SourcceyClientConfig(RobotConfig):
    # Network Configuration
    remote_ip: str
    port_zmq_cmd: int = 5555
    port_zmq_observations: int = 5556
    # SLAM sidecar input stream (sourccey-slam expects slam_input.v1).
    # Canonical config lives under this nested field.
    slam: SlamInputConfig = field(default_factory=SlamInputConfig)
    # Backward-compatibility aliases for existing commands/docs.
    # If provided, these values override the nested slam config in __post_init__.
    slam_input_enabled: bool | None = None
    slam_input_endpoint: str | None = None
    slam_stereo_left_key: str | None = None
    slam_stereo_right_key: str | None = None
    slam_jpeg_quality: int | None = None

    # Q/E position-target generation, deliberately slower than physical full travel.
    z_teleop_full_travel_s: float = 8.0
    z_teleop_max_target_step: float = 2.0

    teleop_keys: dict[str, str] = field(
        default_factory=lambda: {
            # Movement
            "forward": "w",
            "backward": "s",
            "left": "a",
            "right": "d",
            "rotate_left": "z",
            "rotate_right": "x",
            "up": "q",
            "down": "e",
            # Speed control
            "speed_up": "r",
            "speed_down": "f",
            # Host control (toggle per-arm untorque)
            "untorque_left": "n",
            "untorque_right": "m",
            # quit teleop
            "quit": "space",
        }
    )

    cameras: dict[str, CameraConfig] = field(default_factory=sourccey_cameras_config)

    polling_timeout_ms: int = 15
    # By default, fall back to the last received remote observation when no fresh
    # packet is available yet. Enable this only when you explicitly want strict
    # freshness enforcement during debugging.
    wait_for_fresh_observation: bool = False
    # Upper bound on how long get_observation() will wait for a fresh packet before
    # raising an error rather than serving stale images.
    fresh_observation_timeout_ms: int = 30
    # Toggle periodic timeout logs when no observation packet arrives.
    log_no_data_timeouts: bool = True
    # Minimum interval between timeout log lines (seconds) when logging is enabled.
    no_data_log_interval_s: float = 5.0
    connect_timeout_s: int = 5

    def __post_init__(self) -> None:
        super().__post_init__()

        # Migrate flat legacy flags into nested SLAM config when explicitly provided.
        if self.slam_input_enabled is not None:
            self.slam.input_enabled = self.slam_input_enabled
        if self.slam_input_endpoint is not None:
            self.slam.input_endpoint = self.slam_input_endpoint
        if self.slam_stereo_left_key is not None:
            self.slam.stereo_left_key = self.slam_stereo_left_key
        if self.slam_stereo_right_key is not None:
            self.slam.stereo_right_key = self.slam_stereo_right_key
        if self.slam_jpeg_quality is not None:
            self.slam.jpeg_quality = self.slam_jpeg_quality

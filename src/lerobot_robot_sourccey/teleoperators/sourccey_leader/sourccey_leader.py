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
import json
import time
from pathlib import Path

from lerobot.utils.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError
from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import (
    FeetechMotorsBus,
    OperatingMode,
)

from lerobot.teleoperators.teleoperator import Teleoperator
from .config_sourccey_leader import  SourcceyLeaderConfig
from .sourccey_leader_calibrator import SourcceyLeaderCalibrator

logger = logging.getLogger(__name__)


class SourcceyLeader(Teleoperator):
    """
    [Sourccey Leader Teleoperator] designed by Vulcan
    """

    config_class = SourcceyLeaderConfig
    name = "sourccey_leader"

    def __init__(self, config: SourcceyLeaderConfig):
        super().__init__(config)
        self.config = config

        motor_ids = [1, 2, 3, 4, 5, 6]
        if self.config.orientation == "right":
            motor_ids = [7, 8, 9, 10, 11, 12]

        self.bus = FeetechMotorsBus(
            port=self.config.port,
            motors={
                "shoulder_pan": Motor(motor_ids[0], "sts3215", MotorNormMode.RANGE_M100_100),
                "shoulder_lift": Motor(motor_ids[1], "sts3215", MotorNormMode.RANGE_M100_100),
                "elbow_flex": Motor(motor_ids[2], "sts3215", MotorNormMode.RANGE_M100_100),
                "wrist_flex": Motor(motor_ids[3], "sts3215", MotorNormMode.RANGE_M100_100),
                "wrist_roll": Motor(motor_ids[4], "sts3215", MotorNormMode.RANGE_M100_100),
                "gripper": Motor(motor_ids[5], "sts3215", MotorNormMode.RANGE_0_100),
            },
            calibration=self.calibration,
        )

        # Connection
        self.leader_connected = False
        self.using_arm = False

        # Initialize calibrator for automatic calibration
        self.calibrator = SourcceyLeaderCalibrator(self)

        # Load default action file
        self._default_action = self._load_default_action()
        self._default_active_action = self._load_default_active_action()

        # Track last warning time for throttling
        self._last_warning_time = 0.0
        self._warning_throttle_interval = 60.0  # seconds
        self._last_disconnected_warning_time = 0.0
        self._disconnected_warning_throttle_interval = 5.0  # seconds

    def _load_default_action(self) -> dict[str, float]:
        """Load default action from JSON file."""
        current_dir = Path(__file__).parent
        if self.config.orientation == "right":
            action_file = current_dir / "defaults" / "right_arm_default_action.json"
        else:
            action_file = current_dir / "defaults" / "left_arm_default_action.json"

        if action_file.exists():
            with open(action_file, "r") as f:
                return json.load(f)
        else:
            logger.warning(f"Default action file not found: {action_file}. Using zero positions.")
            # Fallback to zero positions if file doesn't exist
            return {f"{motor}.pos": 0.0 for motor in self.bus.motors}

    def _load_default_active_action(self) -> dict[str, float]:
        """Load default active action from JSON file."""
        current_dir = Path(__file__).parent
        if self.config.orientation == "right":
            action_file = current_dir / "defaults" / "right_arm_default_active_action.json"
        else:
            action_file = current_dir / "defaults" / "left_arm_default_active_action.json"
        if action_file.exists():
            with open(action_file, "r") as f:
                return json.load(f)
        else:
            logger.warning(f"Default active action file not found: {action_file}. Using zero positions.")
            # Fallback to zero positions if file doesn't exist
            return {f"{motor}.pos": 0.0 for motor in self.bus.motors}

    @property
    def action_features(self) -> dict[str, type]:
        return {f"{motor}.pos": float for motor in self.bus.motors}

    @property
    def feedback_features(self) -> dict[str, type]:
        return {}

    @property
    def is_connected(self) -> bool:
        return self.bus.is_connected and self.leader_connected

    def connect(self, calibrate: bool = True) -> None:
        if self.is_connected:
            raise DeviceAlreadyConnectedError(f"{self} already connected")

        self.bus.connect()
        if not self.is_calibrated and calibrate:
            self.calibrate()

        self.configure()

        self.leader_connected = True
        self.using_arm = True
        logger.info(f"{self} connected.")

    def disconnect(self) -> None:
        if not self.is_connected:
            DeviceNotConnectedError(f"{self} is not connected.")

        self.bus.disconnect()
        logger.info(f"{self} disconnected.")

    @property
    def is_calibrated(self) -> bool:
        return self.bus.is_calibrated

    def calibrate(self) -> None:
        if self.calibration:
            logger.info(f"Writing calibration file associated with the id {self.id} to the motors")
            self.bus.write_calibration(self.calibration)
            return

        logger.info(f"\nRunning calibration of {self}")
        self.bus.disable_torque()
        for motor in self.bus.motors:
            self.bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)

        input(f"Move {self} to the middle of its range of motion and press ENTER....")
        homing_offsets = self.bus.set_half_turn_homings()

        full_turn_motor = "wrist_roll"
        unknown_range_motors = [motor for motor in self.bus.motors if motor != full_turn_motor]
        print(
            f"Move all joints except '{full_turn_motor}' sequentially through their "
            "entire ranges of motion.\nRecording positions. Press ENTER to stop..."
        )
        range_mins, range_maxes = self.bus.record_ranges_of_motion(unknown_range_motors)
        range_mins[full_turn_motor] = 0
        range_maxes[full_turn_motor] = 4095

        self.calibration = {}
        for motor, m in self.bus.motors.items():
            self.calibration[motor] = MotorCalibration(
                id=m.id,
                drive_mode=0,
                homing_offset=homing_offsets[motor],
                range_min=range_mins[motor],
                range_max=range_maxes[motor],
            )

        self.bus.write_calibration(self.calibration)
        self._save_calibration()
        print(f"Calibration saved to {self.calibration_fpath}")

    def auto_calibrate(self, reverse: bool = False, full_reset: bool = False) -> None:
        """Perform automatic calibration."""
        self.calibration = self.calibrator.default_calibrate(reverse=reverse)

    def configure(self) -> None:
        self.bus.disable_torque()
        self.bus.configure_motors()
        for motor in self.bus.motors:
            self.bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)

    def setup_motors(self) -> None:
        for motor in reversed(self.bus.motors):
            input(f"Connect the controller board to the '{motor}' motor only and press enter.")
            self.bus.setup_motor(motor)
            print(f"'{motor}' motor id set to {self.bus.motors[motor].id}")

    def get_action(self) -> dict[str, float]:
        if not self.is_connected:
            if self.using_arm:
                self._log_disconnected_warning_throttled()
            return self._default_active_action if self.using_arm else self._default_action

        try:
            action = self.bus.sync_read("Present_Position")
            action = {f"{motor}.pos": val for motor, val in action.items()}
            return action
        except ConnectionError as e:
            current_time = time.time()
            # Only log warning if enough time has passed since last warning
            if current_time - self._last_warning_time >= self._warning_throttle_interval:
                logger.warning(f"Status packet error in {self}: {e}. Returning default action.")
                self._last_warning_time = current_time
            return self._default_active_action if self.using_arm else self._default_action

    def send_feedback(self, feedback: dict[str, float]) -> None:
        raise NotImplementedError

    def _log_disconnected_warning_throttled(self) -> None:
        current_time = time.monotonic()
        if (
            current_time - self._last_disconnected_warning_time
            < self._disconnected_warning_throttle_interval
        ):
            return

        disconnected_components = []
        if not self.bus.is_connected:
            disconnected_components.append(f"motor bus on port '{self.config.port}'")
        if not self.leader_connected:
            disconnected_components.append("leader connection state")

        logger.warning(
            "%s Sourccey leader is disconnected (%s). Returning default active action.",
            self.config.orientation.capitalize(),
            ", ".join(disconnected_components),
        )
        self._last_disconnected_warning_time = current_time


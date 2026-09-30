import logging
from typing import Any

import cv2
import numpy as np

from .generated import sourccey_pb2

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1

_LEFT_ARM_FIELDS = {
    "left_shoulder_pan.pos": "shoulder_pan",
    "left_shoulder_lift.pos": "shoulder_lift",
    "left_elbow_flex.pos": "elbow_flex",
    "left_wrist_flex.pos": "wrist_flex",
    "left_wrist_roll.pos": "wrist_roll",
    "left_gripper.pos": "gripper",
}
_RIGHT_ARM_FIELDS = {
    "right_shoulder_pan.pos": "shoulder_pan",
    "right_shoulder_lift.pos": "shoulder_lift",
    "right_elbow_flex.pos": "elbow_flex",
    "right_wrist_flex.pos": "wrist_flex",
    "right_wrist_roll.pos": "wrist_roll",
    "right_gripper.pos": "gripper",
}
_BASE_VELOCITY_FIELDS = {
    "x.vel": "x_vel",
    "y.vel": "y_vel",
    "theta.vel": "theta_vel",
}
_BASE_POSITION_FIELDS = {"z.pos": "z_pos"}
_CONTROL_FIELDS = ("untorque_left", "untorque_right")
_ACTION_FIELDS = {
    **_LEFT_ARM_FIELDS,
    **_RIGHT_ARM_FIELDS,
    **_BASE_VELOCITY_FIELDS,
    **_BASE_POSITION_FIELDS,
}
_ACTION_FIELDS.update({key: key for key in _CONTROL_FIELDS})


class SourcceyProtobuf:
    """Handles protobuf conversion for Sourccey robot actions and observations."""

    def __init__(self):
        pass

    def action_to_protobuf(self, action: dict[str, Any]) -> sourccey_pb2.SourcceyRobotAction:
        """Convert an action patch without inventing values for omitted fields."""
        try:
            unsupported = set(action).difference(_ACTION_FIELDS, {"action"})
            if unsupported:
                raise ValueError(f"Unsupported Sourccey action fields: {sorted(unsupported)}")

            robot_action = sourccey_pb2.SourcceyRobotAction()
            robot_action.protocol_version = PROTOCOL_VERSION

            update_fields = [key for key in _ACTION_FIELDS if key in action]
            robot_action.update_fields.extend(update_fields)

            # Process left arm action
            left_fields = [key for key in _LEFT_ARM_FIELDS if key in action]
            if left_fields:
                left_target_positions = sourccey_pb2.MotorJoint()
                for key in left_fields:
                    setattr(left_target_positions, _LEFT_ARM_FIELDS[key], float(action[key]))
                robot_action.left_arm_target_joints.CopyFrom(left_target_positions)

            # Process right arm action
            right_fields = [key for key in _RIGHT_ARM_FIELDS if key in action]
            if right_fields:
                right_target_positions = sourccey_pb2.MotorJoint()
                for key in right_fields:
                    setattr(right_target_positions, _RIGHT_ARM_FIELDS[key], float(action[key]))
                robot_action.right_arm_target_joints.CopyFrom(right_target_positions)

            # Process base action
            velocity_fields = [key for key in _BASE_VELOCITY_FIELDS if key in action]
            if velocity_fields:
                base_action = sourccey_pb2.BaseVelocity()
                for key in velocity_fields:
                    setattr(base_action, _BASE_VELOCITY_FIELDS[key], float(action[key]))
                robot_action.base_target_velocity.CopyFrom(base_action)

            if "z.pos" in action:
                base_pos = sourccey_pb2.BasePosition()
                base_pos.z_pos = float(action["z.pos"])
                robot_action.base_target_position.CopyFrom(base_pos)

            # Per-arm flags
            if "untorque_left" in action:
                robot_action.untorque_left = bool(action["untorque_left"])
            if "untorque_right" in action:
                robot_action.untorque_right = bool(action["untorque_right"])

            return robot_action

        except ImportError as e:
            logger.error(f"Failed to import protobuf modules: {e}")
            logger.error("Run the protobuf setup script first: python src/lerobot/robots/sourccey/sourccey/protobuf/compile.py")
            raise
        except Exception as e:
            logger.error(f"Failed to convert action to protobuf: {e}")
            raise

    def observation_to_protobuf(self, observation: dict[str, Any]) -> sourccey_pb2.SourcceyRobotState:
        """Convert observation dictionary to protobuf SourcceyRobotState message."""
        try:
            msg = sourccey_pb2.SourcceyRobotState()
            msg.protocol_version = PROTOCOL_VERSION

            # Set left arm motor positions
            left_motor_pos = msg.left_arm_joints
            left_motor_pos.shoulder_pan = observation.get("left_shoulder_pan.pos", 0.0)
            left_motor_pos.shoulder_lift = observation.get("left_shoulder_lift.pos", 0.0)
            left_motor_pos.elbow_flex = observation.get("left_elbow_flex.pos", 0.0)
            left_motor_pos.wrist_flex = observation.get("left_wrist_flex.pos", 0.0)
            left_motor_pos.wrist_roll = observation.get("left_wrist_roll.pos", 0.0)
            left_motor_pos.gripper = observation.get("left_gripper.pos", 0.0)

            # Set right arm motor positions
            right_motor_pos = msg.right_arm_joints
            right_motor_pos.shoulder_pan = observation.get("right_shoulder_pan.pos", 0.0)
            right_motor_pos.shoulder_lift = observation.get("right_shoulder_lift.pos", 0.0)
            right_motor_pos.elbow_flex = observation.get("right_elbow_flex.pos", 0.0)
            right_motor_pos.wrist_flex = observation.get("right_wrist_flex.pos", 0.0)
            right_motor_pos.wrist_roll = observation.get("right_wrist_roll.pos", 0.0)
            right_motor_pos.gripper = observation.get("right_gripper.pos", 0.0)

            # Set base velocity
            base_vel = msg.base_velocity
            base_vel.x_vel = observation.get("x.vel", 0.0)
            base_vel.y_vel = observation.get("y.vel", 0.0)
            base_vel.theta_vel = observation.get("theta.vel", 0.0)

            # Set base position (linear actuator)
            base_pos = msg.base_position
            base_pos.z_pos = observation.get("z.pos", 0.0)

            # Process cameras - convert numpy arrays to CameraImage messages
            for cam_key, cam_data in observation.items():
                if isinstance(cam_data, np.ndarray):
                    camera = sourccey_pb2.CameraImage()
                    camera.name = cam_key
                    # Encode as JPEG and store raw bytes
                    _, encoded_img = cv2.imencode('.jpg', cam_data)
                    camera.image_data = encoded_img.tobytes()
                    msg.cameras.append(camera)

            return msg

        except ImportError as e:
            logger.error(f"Failed to import protobuf modules: {e}")
            logger.error("Run the protobuf setup script first: python src/lerobot/robots/sourccey/sourccey/protobuf/compile.py")
            raise
        except Exception as e:
            logger.error(f"Failed to convert observation to protobuf: {e}")
            raise

    def protobuf_to_action(self, action_msg: sourccey_pb2.SourcceyRobotAction) -> dict[str, Any]:
        """Convert a versioned protobuf action patch to its supplied fields."""
        try:
            if action_msg.protocol_version != PROTOCOL_VERSION:
                raise ValueError(
                    "Unsupported Sourccey command protocol version "
                    f"{action_msg.protocol_version}; expected {PROTOCOL_VERSION}."
                )

            update_fields = list(action_msg.update_fields)
            unsupported = set(update_fields).difference(_ACTION_FIELDS)
            if unsupported:
                raise ValueError(f"Unsupported Sourccey action fields: {sorted(unsupported)}")
            if len(update_fields) != len(set(update_fields)):
                raise ValueError("Sourccey action update_fields contains duplicates")

            action: dict[str, Any] = {}

            # Convert left arm action
            left_fields = [key for key in update_fields if key in _LEFT_ARM_FIELDS]
            if left_fields and not action_msg.HasField("left_arm_target_joints"):
                raise ValueError("Sourccey action is missing its left-arm payload")
            for key in left_fields:
                action[key] = getattr(action_msg.left_arm_target_joints, _LEFT_ARM_FIELDS[key])

            # Convert right arm action
            right_fields = [key for key in update_fields if key in _RIGHT_ARM_FIELDS]
            if right_fields and not action_msg.HasField("right_arm_target_joints"):
                raise ValueError("Sourccey action is missing its right-arm payload")
            for key in right_fields:
                action[key] = getattr(action_msg.right_arm_target_joints, _RIGHT_ARM_FIELDS[key])

            # Convert base action
            velocity_fields = [key for key in update_fields if key in _BASE_VELOCITY_FIELDS]
            if velocity_fields and not action_msg.HasField("base_target_velocity"):
                raise ValueError("Sourccey action is missing its base-velocity payload")
            for key in velocity_fields:
                action[key] = getattr(action_msg.base_target_velocity, _BASE_VELOCITY_FIELDS[key])

            if "z.pos" in update_fields:
                if not action_msg.HasField("base_target_position"):
                    raise ValueError("Sourccey action is missing its base-position payload")
                action["z.pos"] = action_msg.base_target_position.z_pos

            if "untorque_left" in update_fields:
                action["untorque_left"] = bool(action_msg.untorque_left)
            if "untorque_right" in update_fields:
                action["untorque_right"] = bool(action_msg.untorque_right)

            return action

        except ImportError as e:
            logger.error(f"Failed to import protobuf modules: {e}")
            logger.error("Run the protobuf setup script first: python src/lerobot/robots/sourccey/sourccey/protobuf/compile.py")
            raise
        except Exception as e:
            logger.error(f"Failed to convert protobuf to action: {e}")
            raise

    def protobuf_to_observation(self, robot_state: sourccey_pb2.SourcceyRobotState) -> dict[str, Any]:
        """Convert protobuf SourcceyRobotState message to observation dictionary."""
        try:
            observation = {}

            # Process left arm state
            left_motor_pos = robot_state.left_arm_joints
            observation["left_shoulder_pan.pos"] = left_motor_pos.shoulder_pan
            observation["left_shoulder_lift.pos"] = left_motor_pos.shoulder_lift
            observation["left_elbow_flex.pos"] = left_motor_pos.elbow_flex
            observation["left_wrist_flex.pos"] = left_motor_pos.wrist_flex
            observation["left_wrist_roll.pos"] = left_motor_pos.wrist_roll
            observation["left_gripper.pos"] = left_motor_pos.gripper

            # Process right arm state
            right_motor_pos = robot_state.right_arm_joints
            observation["right_shoulder_pan.pos"] = right_motor_pos.shoulder_pan
            observation["right_shoulder_lift.pos"] = right_motor_pos.shoulder_lift
            observation["right_elbow_flex.pos"] = right_motor_pos.elbow_flex
            observation["right_wrist_flex.pos"] = right_motor_pos.wrist_flex
            observation["right_wrist_roll.pos"] = right_motor_pos.wrist_roll
            observation["right_gripper.pos"] = right_motor_pos.gripper

            # Process base velocity
            base_vel = robot_state.base_velocity
            observation["x.vel"] = base_vel.x_vel
            observation["y.vel"] = base_vel.y_vel
            observation["theta.vel"] = base_vel.theta_vel

            # Z position (linear actuator)
            observation["z.pos"] = robot_state.base_position.z_pos

            # Process cameras from the cameras list
            for camera in robot_state.cameras:
                if camera.image_data:
                    try:
                        nparr = np.frombuffer(camera.image_data, np.uint8)
                        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if frame is not None:
                            observation[camera.name] = frame
                    except Exception as e:
                        logger.warning(f"Failed to decode camera image {camera.name}: {e}")

            return observation

        except ImportError as e:
            logger.error(f"Failed to import protobuf modules: {e}")
            logger.error("Run the protobuf setup script first: python src/lerobot/robots/sourccey/sourccey/protobuf/compile.py")
            raise
        except Exception as e:
            logger.error(f"Failed to convert protobuf to observation: {e}")
            raise

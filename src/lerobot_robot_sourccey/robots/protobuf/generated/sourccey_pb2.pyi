from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CameraImage(_message.Message):
    __slots__ = ("name", "image_data")
    NAME_FIELD_NUMBER: _ClassVar[int]
    IMAGE_DATA_FIELD_NUMBER: _ClassVar[int]
    name: str
    image_data: bytes
    def __init__(self, name: _Optional[str] = ..., image_data: _Optional[bytes] = ...) -> None: ...

class MotorJoint(_message.Message):
    __slots__ = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    SHOULDER_PAN_FIELD_NUMBER: _ClassVar[int]
    SHOULDER_LIFT_FIELD_NUMBER: _ClassVar[int]
    ELBOW_FLEX_FIELD_NUMBER: _ClassVar[int]
    WRIST_FLEX_FIELD_NUMBER: _ClassVar[int]
    WRIST_ROLL_FIELD_NUMBER: _ClassVar[int]
    GRIPPER_FIELD_NUMBER: _ClassVar[int]
    shoulder_pan: float
    shoulder_lift: float
    elbow_flex: float
    wrist_flex: float
    wrist_roll: float
    gripper: float
    def __init__(self, shoulder_pan: _Optional[float] = ..., shoulder_lift: _Optional[float] = ..., elbow_flex: _Optional[float] = ..., wrist_flex: _Optional[float] = ..., wrist_roll: _Optional[float] = ..., gripper: _Optional[float] = ...) -> None: ...

class BaseVelocity(_message.Message):
    __slots__ = ("x_vel", "y_vel", "theta_vel")
    X_VEL_FIELD_NUMBER: _ClassVar[int]
    Y_VEL_FIELD_NUMBER: _ClassVar[int]
    THETA_VEL_FIELD_NUMBER: _ClassVar[int]
    x_vel: float
    y_vel: float
    theta_vel: float
    def __init__(self, x_vel: _Optional[float] = ..., y_vel: _Optional[float] = ..., theta_vel: _Optional[float] = ...) -> None: ...

class BasePosition(_message.Message):
    __slots__ = ("z_pos",)
    Z_POS_FIELD_NUMBER: _ClassVar[int]
    z_pos: float
    def __init__(self, z_pos: _Optional[float] = ...) -> None: ...

class SourcceyRobotState(_message.Message):
    __slots__ = ("left_arm_joints", "right_arm_joints", "base_position", "base_velocity", "cameras")
    LEFT_ARM_JOINTS_FIELD_NUMBER: _ClassVar[int]
    RIGHT_ARM_JOINTS_FIELD_NUMBER: _ClassVar[int]
    BASE_POSITION_FIELD_NUMBER: _ClassVar[int]
    BASE_VELOCITY_FIELD_NUMBER: _ClassVar[int]
    CAMERAS_FIELD_NUMBER: _ClassVar[int]
    left_arm_joints: MotorJoint
    right_arm_joints: MotorJoint
    base_position: BasePosition
    base_velocity: BaseVelocity
    cameras: _containers.RepeatedCompositeFieldContainer[CameraImage]
    def __init__(self, left_arm_joints: _Optional[_Union[MotorJoint, _Mapping]] = ..., right_arm_joints: _Optional[_Union[MotorJoint, _Mapping]] = ..., base_position: _Optional[_Union[BasePosition, _Mapping]] = ..., base_velocity: _Optional[_Union[BaseVelocity, _Mapping]] = ..., cameras: _Optional[_Iterable[_Union[CameraImage, _Mapping]]] = ...) -> None: ...

class SourcceyRobotAction(_message.Message):
    __slots__ = ("left_arm_target_joints", "right_arm_target_joints", "base_target_position", "base_target_velocity", "untorque_left", "untorque_right")
    LEFT_ARM_TARGET_JOINTS_FIELD_NUMBER: _ClassVar[int]
    RIGHT_ARM_TARGET_JOINTS_FIELD_NUMBER: _ClassVar[int]
    BASE_TARGET_POSITION_FIELD_NUMBER: _ClassVar[int]
    BASE_TARGET_VELOCITY_FIELD_NUMBER: _ClassVar[int]
    UNTORQUE_LEFT_FIELD_NUMBER: _ClassVar[int]
    UNTORQUE_RIGHT_FIELD_NUMBER: _ClassVar[int]
    left_arm_target_joints: MotorJoint
    right_arm_target_joints: MotorJoint
    base_target_position: BasePosition
    base_target_velocity: BaseVelocity
    untorque_left: bool
    untorque_right: bool
    def __init__(self, left_arm_target_joints: _Optional[_Union[MotorJoint, _Mapping]] = ..., right_arm_target_joints: _Optional[_Union[MotorJoint, _Mapping]] = ..., base_target_position: _Optional[_Union[BasePosition, _Mapping]] = ..., base_target_velocity: _Optional[_Union[BaseVelocity, _Mapping]] = ..., untorque_left: bool = ..., untorque_right: bool = ...) -> None: ...

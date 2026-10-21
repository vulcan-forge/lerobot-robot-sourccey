"""Canonical follower-arm motor layout shared by hardware and policy adapters."""


def sourccey_motor_models() -> dict[str, str]:
    return {
        "shoulder_pan": "sts3215",
        "shoulder_lift": "sts3250",
        "elbow_flex": "sts3250",
        "wrist_flex": "sts3215",
        "wrist_roll": "sts3215",
        "gripper": "sts3215",
    }

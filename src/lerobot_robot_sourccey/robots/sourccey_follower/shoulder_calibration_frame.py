"""Place the right shoulder's encoder seam outside its calibrated travel."""

from dataclasses import replace

from lerobot.motors.motors_bus import MotorCalibration

ENCODER_PERIOD = 4096
ENCODER_MAX = ENCODER_PERIOD - 1
MAX_HOMING_OFFSET = 2047
UNREPRESENTABLE_OFFSET = ENCODER_PERIOD // 2


def center_right_shoulder_frame(calibration: MotorCalibration) -> MotorCalibration:
    """Center a right shoulder's range in its own single-turn encoder frame.

    The chosen homing offset is derived from this calibration rather than from
    another robot. Both endpoints move by the same amount, preserving every
    physical target and normalized coordinate. Candidate frames that put a
    calibrated endpoint on the 4095/0 seam are excluded.
    """
    if calibration.id != 8:
        raise ValueError("Right-shoulder frame selection requires motor ID 8")

    low = calibration.range_min
    high = calibration.range_max
    offset = calibration.homing_offset
    if any(type(value) is not int for value in (low, high, offset)):
        raise ValueError("Shoulder calibration values must be integer ticks")
    if (
        not -MAX_HOMING_OFFSET <= offset <= MAX_HOMING_OFFSET
        or not 0 <= low < high <= ENCODER_MAX
    ):
        raise ValueError(
            "Invalid or wrapped shoulder calibration; do not start the host"
        )

    span = high - low
    candidates: list[tuple[int, int]] = []
    for translated_low in range(1, ENCODER_MAX - span):
        offset_residue = (low + offset - translated_low) % ENCODER_PERIOD
        if offset_residue == UNREPRESENTABLE_OFFSET:
            continue
        translated_high = translated_low + span
        clearance = min(translated_low, ENCODER_MAX - translated_high)
        candidates.append((clearance, translated_low))

    if not candidates:
        raise ValueError(
            "Right shoulder has no representable encoder frame with the seam outside its calibrated range"
        )

    _, translated_low = max(
        candidates, key=lambda candidate: (candidate[0], -candidate[1])
    )
    translated_high = translated_low + span
    offset_residue = (low + offset - translated_low) % ENCODER_PERIOD
    target_offset = (
        offset_residue
        if offset_residue <= MAX_HOMING_OFFSET
        else offset_residue - ENCODER_PERIOD
    )

    return replace(
        calibration,
        homing_offset=target_offset,
        range_min=translated_low,
        range_max=translated_high,
    )

# Right shoulder encoder-seam fix

This note documents a Sourccey right `shoulder_lift` failure in which the arm
can start near the STS3250 single-turn encoder seam and appear to jump from one
end of its calibrated coordinates to the other. It also documents the automatic
repair in `shoulder_calibration_frame.py` so a future operator or debugging
agent can distinguish this issue from a model failure.

## Failure signature

The motor reports one revolution as values `0` through `4095`. The physical
shoulder is geared and mechanically bounded, but its configured coordinate seam
can sit close to a reachable starting pose. When the arm starts just across that
seam, feedback can change from approximately `4095` to `0`. Normalization then
makes a physically small crossing look like a jump between approximately `-100`
and `+100`.

After that false jump, an ordinary normalized target can become a goal near the
opposite end of the single-turn coordinates. The result looks like a commanded
shoulder flip even though the model did not produce such a physical movement.

The strongest identifying clues are:

- The issue depends on the shoulder's pose when the host starts.
- Crossing the old seam after a normal startup may not reproduce it.
- Raw `Present_Position` crosses `4095 -> 0` or `0 -> 4095` while the physical
  joint moves only slightly.
- Normalized `right_shoulder_lift.pos` jumps between values near `-100` and
  `+100`.
- The other joints keep receiving small, plausible commands while the right
  shoulder tries to reach an implausible goal.

## What the fix does

The fix does not guess or share a numeric offset between robots. During every
new right-arm calibration, it uses that robot's measured homing offset and
calibrated mechanical range to select the representable encoder frame with the
greatest clearance between the range and the `4095 -> 0` seam.

For each possible safe frame, the equivalent range begins at:

```text
new_minimum = (minimum + old_offset - new_offset) mod 4096
new_maximum = new_minimum + (maximum - minimum)
```

The implementation chooses the frame that maximizes the smaller of the lower
and upper seam clearances. It excludes the STS3250's unrepresentable `2048`
homing offset and any frame that puts a calibrated endpoint on the seam.

Because both endpoints move by exactly the same amount, this preserves:

- every calibrated physical angle;
- the calibrated span and joint direction;
- the mapping between physical positions and normalized values;
- existing model and teleoperation behavior inside the calibrated range.

Only the numerical location of the encoder seam changes. Invalid, wrapped, or
seam-filling ranges fail calibration instead of being clipped or saved.

## Applying it to a fleet

There is no robot-specific constant or sidecar file. Each robot calculates and
saves its own correct offset as part of right-arm calibration. Different robots
can therefore select different numeric offsets while keeping identical logical
joint behavior.

This protection is enabled by default. Normal calibration commands require no
new flag or operator-supplied value. The advanced follower configuration field
`protect_right_shoulder_encoder_seam` and whole-robot field
`right_arm_protect_shoulder_encoder_seam` both default to `true`; disabling
them is intended only for controlled diagnostics or incompatible replacement
hardware.

After installing this version on an already calibrated robot, stop
`sourccey-host`, clear and support the arms, and run once:

```bash
uv run sourccey-calibrate --arm right
```

Use `--full-reset --yes` only when the physical mechanical range itself needs
to be redetected. Future default and full calibrations automatically recalculate
the safe frame; no value needs to be copied between robots.

Calibration releases arm torque before changing position references. The arms
can fall, so support them and keep the workspace clear.

## What this fix does not do

- It does not create a mechanical limit or certify the robot's safe travel.
- It does not make a single-turn position servo into a multi-turn servo.
- It does not choose circular shortest paths for arbitrary goals.
- It does not repair corrupt packets, damaged encoders, loose gears, or a motor
  whose internal reference changes while powered.
- It cannot create seam clearance if a recorded range consumes essentially the
  entire encoder revolution; calibration fails in that case.

## If the problem happens again

Stop inference and the robot host. Do not repeatedly restart into the bad pose.
Preserve the following before recalibrating or editing registers:

1. The right-arm calibration JSON.
2. The exact package version or Git commit running on the robot.
3. Host logs covering calibration, startup, and the first unexpected movement.
4. Raw motor-8 values for `Present_Position`, `Goal_Position`,
   `Homing_Offset`, `Min_Position_Limit`, `Max_Position_Limit`,
   `Operating_Mode`, `Phase`, `Torque_Enable`, and `Status`.
5. Desktop policy targets and normalized shoulder observations from the same
   timestamps.
6. Whether the arm started beyond either calibrated endpoint and whether the
   failure occurred before or after crossing the encoder seam.

Then verify offline that the right shoulder is STS3250 motor ID 8, calibration
has ordered integer endpoints within `0..4095`, both endpoints have positive
seam clearance, the span and normalized mapping are unchanged, and no package
reinstall replaced this implementation with an older release.

The focused regression tests are in
`tests/test_shoulder_calibration_frame.py`. They exercise two different robot
alignments, exact automatic selection, every-tick physical and normalized
equivalence, idempotence, the unrepresentable-offset edge case, both automatic
calibration paths, invalid ranges, and fail-fast checks without opening a motor
bus.

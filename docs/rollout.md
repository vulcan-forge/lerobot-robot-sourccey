# Policy rollout and desktop shutdown

Install the desktop profile against the integrated LeRobot checkout:

```powershell
uv pip install -e "../packages/lerobot-robot-sourccey[desktop]"
uv run --no-sync sourccey-rollout --help
```

`sourccey-rollout` uses LeRobot's public rollout context, inference engines,
strategies, and recording teardown. It adds `shutdown_event_path`: creating that
file sets the normal shutdown event, allowing the active strategy to finalize its
dataset. Its watcher stops on success, failure, or interruption. Vulcan Studio's
rollout and inference launchers use this package command. Standard
`lerobot-rollout` remains available when desktop stop-file control is unnecessary.

The command needs the LeRobot 0.6.2 rollout API. Basic hardware, recording, and
teleoperation integrations continue to support LeRobot 0.6.1. The package's
`rollout` extra declares this difference explicitly; no upstream globals are
patched.

## Unavailable follower arms

The host normally publishes `NaN` for unavailable follower joints. It skips
commands to disconnected arms, while the connected arm, base, and lift keep
working. Standard policy inference correctly rejects those missing measurements.

For a policy intended to operate without an arm, configure a complete placeholder
pose for that arm on the **client**. These values must match the policy's training
units and intended missing-arm pose. They are synthetic policy inputs, not
measurements. A policy trained to require both physical arms is not made suitable
for one-arm operation by this adapter.

For example, put this in `rollout.yaml`, replacing the IP and example pose with
your policy's configuration:

```yaml
robot:
  type: sourccey_client
  remote_ip: 192.168.1.50
  missing_arm_positions:
    left_shoulder_pan.pos: 0.0
    left_shoulder_lift.pos: 0.0
    left_elbow_flex.pos: 0.0
    left_wrist_flex.pos: 0.0
    left_wrist_roll.pos: 0.0
    left_gripper.pos: 0.0
strategy:
  type: base
task: Move the object with the right arm
shutdown_event_path: rollout.stop
```

```powershell
uv run --no-sync sourccey-rollout --config_path=rollout.yaml --policy.path=path/to/pretrained_model
```

Configure right-arm keys as well if both arms may be absent. The adapter only
substitutes a complete all-`NaN` arm. Partial, infinite, or incomplete telemetry
fails rather than mixing real and invented joint measurements. Commands and
torque flags for substituted arms are removed, and their protobuf target messages
are omitted. The host decoder respects that omission. Deploy the updated package
to both the desktop and host for this contract.

Leave the host's `missing_arm_positions` empty to preserve raw telemetry and
diagnostics. Direct local rollout with `robot.type=sourccey` can use the same
explicit mapping. Do not enable placeholders when recording measurements for
training. Defaults remain empty; no zero pose is silently invented. Arm hardware
does not reconnect automatically: reconnect the robot after restoring it.

## Calibration recovery and homing

Sourccey followers, leaders, composite robots, and clients share a package-owned
calibration loader. Malformed JSON or invalid calibration fields leave the device
uncalibrated and produce a warning. The original file is preserved. Permission
and disk I/O failures propagate so they can be corrected.

Position homing lives exclusively in `lerobot_robot_sourccey.motors.homing` and
uses public motor-bus methods. LeRobot's base classes contain no Sourccey fallback
or homing compatibility code.

## Workspace dependency

The Vulcan development checkout resolves Sourccey to the editable sibling package
and locks its current development version. Keep that directory layout when using
`uv sync --locked`. For distribution, publish the reviewed package and replace the
local source with that release; the development version is not a published tag.

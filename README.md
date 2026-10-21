# Sourccey for LeRobot

`lerobot_robot_sourccey` is a third-party LeRobot plugin for the Sourccey
robot and its leader-arm teleoperator. It works with LeRobot without requiring
Sourccey source files or patches inside the LeRobot repository.

## Operation without follower arms

The physical robot connects each follower arm independently. By default,
`SourcceyConfig.allow_partial_connection=True` allows startup with one or both
arms unavailable, while base, lift, and cameras continue operating. Failed arm
connections are logged; `robot.available_arms` reports each arm's connection
state. Commands and torque changes skip disconnected arms, and calibration of
the whole robot operates only on connected arms. Explicitly selecting an absent
arm for auto-calibration raises a connection error.

Unavailable joint observations retain their existing keys with `NaN` values,
including over the protobuf connection. These are missing measurements and
must not be used as valid joint positions for training or policy execution.
Set `allow_partial_connection=False` to require both arms at startup. Reconnect
the robot after restoring an absent arm; automatic arm reconnection is not provided.

## Python SDK quickstart

The customer-facing helpers live in `lerobot_robot_sourccey.sdk` and are also
available directly from the package:

```python
from lerobot_robot_sourccey import SourcceySDK

with SourcceySDK.from_ip("192.168.1.50") as robot:
    observation = robot.get_observation()
    front_left = robot.get_camera("front_left", observation=observation)
    print(front_left.shape)

    robot.drive_for(x=0.2, duration_s=1.0)
```

Base velocities are normalized values from `-1.0` to `1.0`. Timed movement
refreshes the host watchdog and sends an explicit stop when it finishes or is
interrupted.

Runnable and importable examples:

```bash
python examples/sdk_read_observation.py --ip 192.168.1.50
python examples/sdk_camera.py --ip 192.168.1.50 --camera front_left --output front-left.jpg
python examples/sdk_drive_base.py --ip 192.168.1.50 --x 0.2 --duration 1.0
```

## Documentation

| Guide | Use it for |
| --- | --- |
| [Documentation index](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/README.md) | Browse all package documentation |
| [Setup](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/01-setup/README.md) | Install software, prepare hardware, calibrate, and start the host |
| [Control systems](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/02-control-systems/README.md) | Teleoperate, record, replay, and deploy policies |
| [SDK](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/03-sdk/README.md) | Use the Python API, movement helpers, cameras, and 2D LiDAR tools |
| [AI and datasets](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/04-ai/README.md) | Manage datasets and train policies |

For the normal operating path, complete
[Setup](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/01-setup/README.md),
then follow
[Teleoperate](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/02-control-systems/01-teleoperate.md).

## Dataset tools

Install the dataset tooling and use the packaged commands:

```bash
uv pip install -e ".[dataset]"
uv run sourccey-dataset-combine --list-only
uv run sourccey-dataset-audit-consistency --help
uv run sourccey-dataset-audit-videos --help
uv run sourccey-dataset-fix-consistency --help
uv run sourccey-dataset-remove-feature --help
```

The complete combine, audit, repair, and cleanup workflow is documented in
[Dataset tools](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/04-ai/01-datasets.md).

## Registered LeRobot types

| Kind | Type |
| --- | --- |
| Robot | `sourccey` |
| Robot | `sourccey_client` |
| Robot | `sourccey_follower` |
| Teleoperator | `sourccey_leader` |
| Teleoperator | `bi_sourccey_leader` |
| Teleoperator | `sourccey_teleoperator` |

The kiosk manual-drive bridge is available as `sourccey-manual-drive`. It
accepts the existing kiosk arguments, for example:

```bash
sourccey-manual-drive --id=sourccey --remote_ip=127.0.0.1 --udp_port=5561 --fps=30
```

LeRobot discovers the plugin from its `lerobot_robot_sourccey` distribution
and import-package name.

## License

Apache-2.0. Individual source files retain their existing copyright notices.

## Arm motor retries

Sourccey arm buses use five additional transport attempts for reads and writes
by default. These defaults belong to the package; upstream LeRobot motor buses
keep their own defaults. No extra outer retry loop is added.

Leader, follower, bimanual leader, composite teleoperator and robot configs expose
`motor_retries.read` and `motor_retries.write`. For example:

```python
from lerobot_robot_sourccey import SourcceyFollowerConfig
from lerobot_robot_sourccey.motors.retry import MotorRetryPolicy

config = SourcceyFollowerConfig(
    port="/dev/robotLeftArm",
    motor_retries=MotorRetryPolicy(read=2, write=5),
)
```

Both counts must be non-negative integers. Zero requests one attempt with no
retry. A direct bus call with `num_retry=0` (or another explicit count) overrides
the configured budget. Composite configs pass the policy to both arms. Wheel,
lift, camera and network retry behavior is unchanged.

## Camera recovery and desktop controls

Sourccey camera defaults use the registered `sourccey_opencv` camera type.
It retains LeRobot's OpenCV capture settings and frame processing, with a
package-owned reconnect worker. After two consecutive failures it retries
every 50 ms for two seconds, then every 500 ms until recovery or shutdown.
Custom camera dictionaries must use `type: sourccey_opencv` to enable this behavior;
`type: opencv` keeps upstream behavior. Initial connection failures still raise.

Use `sourccey-teleoperate` and `sourccey-record` with
`--teleop.type=sourccey_teleoperator`. These commands reuse LeRobot's control
loops, processors and dataset APIs. They add Sourccey session handling and
observation-aware base/lift controls without modifying upstream globals.

- `--teleop.allow_partial_connection=true` continues with packaged default
  actions for unavailable leader arms, while connecting each remaining arm.
  Set it to `false` to require both leaders.
- `--teleop.allow_keyboard_connection_failure=true` continues with zero
  keyboard movement if local keyboard capture fails. Set it to `false` to
  require keyboard input, or use `--teleop.enable_keyboard=false` to disable it.
- `--teleop.input_state_path=C:/path/keys.json` reads the desktop's JSON list
  of held keys, such as `["w", "r"]`, without requiring a local keyboard listener.
  Missing or malformed files release all keys. Desktop writers should replace
  the file atomically and write `[]` when focus is lost or the session ends.
- An optional `--teleop.input_state_timeout_s=1.0` releases stale input when
  the writer refreshes the snapshot while keys are held. The timeout is disabled
  by default for writers that update only on key transitions.

Right Arrow ends an episode, Left Arrow discards and re-records it, and Escape
stops recording. Movement, speed and untorque keys remain independent of those
episode controls. The lift target initializes from the latest valid observation.
Robot/network connection failures still stop the command.

The desktop application launches these package commands. Install this checkout
with `uv pip install -e "../packages/lerobot-robot-sourccey[desktop]"` in the
LeRobot environment and use `uv run --no-sync` while the release pin still points
to the previously published package. Publishing and updating pins is a separate step.

## Hardware diagnostics

Installed commands cover remote and direct camera checks, motor telemetry and
electrical checks, bottom-camera naming, and LiDAR/IMU health:

```bash
uv run --no-sync sourccey-check-eye-cameras --remote-ip 192.168.1.237 --skip-bottom
uv run --no-sync sourccey-check-arm-cameras --remote-ip 192.168.1.237
uv run --no-sync sourccey-check-eye-cameras-local --include-bottom
uv run --no-sync sourccey-check-arm-cameras-local
uv run --no-sync sourccey-check-bottom-camera --verify-names
uv run --no-sync sourccey-check-motors
uv run --no-sync sourccey-check-lidar-imu
```

Run direct checks on the robot with the host stopped. Remote checks consume only
observations and require the host to be running. Motor motion remains opt-in
through `--wiggle` or `--z-stroke`, with their existing interactive prompts.
See [Hardware checks](docs/01-setup/robot/06-hardware-checks.md) for the complete guide.

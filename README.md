# Sourccey integration for LeRobot

This repository packages the Vulcan Sourccey robots and leader arms as a
third-party [LeRobot](https://github.com/huggingface/lerobot) plugin. Installing
the package makes its device types available to LeRobot's command-line tools;
no changes to the upstream LeRobot source tree are required.

## Requirements

- Python 3.12 or 3.13
- LeRobot 0.6.x
- The appropriate serial devices and permissions for your hardware
- Linux-only GPIO dependencies when controlling the complete Sourccey robot

## Install for development

Create or activate the same Python environment in which you use LeRobot, then
install this repository in editable mode:

```bash
git clone https://github.com/vulcan-forge/lerobot-robot-sourccey.git
cd lerobot-robot-sourccey
python -m pip install -e ".[dev]"
```

For a Linux host that directly controls Sourccey's GPIO hardware:

```bash
python -m pip install -e ".[hardware,dev]"
```

With `uv`, the equivalent command is:

```bash
uv pip install -e ".[hardware,dev]"
```

## Registered device types

| Kind | LeRobot type | Python class |
| --- | --- | --- |
| Robot | `sourccey` | `Sourccey` |
| Robot | `sourccey_client` | `SourcceyClient` |
| Robot | `sourccey_follower` | `SourcceyFollower` |
| Teleoperator | `sourccey_leader` | `SourcceyLeader` |
| Teleoperator | `bi_sourccey_leader` | `BiSourcceyLeader` |

The distribution and import package are both named
`lerobot_robot_sourccey`. The `lerobot_robot_` prefix is intentional:
LeRobot scans installed top-level packages with this prefix and imports this
package, whose `__init__.py` registers all robot and teleoperator configs.

## Example: bimanual teleoperation

Replace the serial ports with the ports reported by your system:

```bash
lerobot-teleoperate \
  --robot.type=sourccey \
  --teleop.type=bi_sourccey_leader \
  --teleop.left_arm_port=/dev/ttyACM0 \
  --teleop.right_arm_port=/dev/ttyACM1
```

To use one follower arm:

```bash
lerobot-teleoperate \
  --robot.type=sourccey_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.orientation=left \
  --teleop.type=sourccey_leader \
  --teleop.port=/dev/ttyACM1 \
  --teleop.orientation=left
```

You can pass the same type names to other LeRobot commands such as
`lerobot-calibrate` and `lerobot-record`.

## Validate the package

```bash
python -m pytest
python -m build
python -m pip install --force-reinstall --no-deps dist/*.whl
python -c "import lerobot_robot_sourccey"
```

The registration tests verify both the LeRobot config registry and the
required `SomethingConfig`/`Something` naming convention.

## Publishing

After updating the version in `pyproject.toml`, build and inspect the
artifacts:

```bash
python -m build
python -m pip install twine
python -m twine check dist/*
```

Upload to TestPyPI first, validate a clean installation, and then publish the
same artifacts to PyPI. The eventual user installation will be:

```bash
python -m pip install lerobot_robot_sourccey
```

## License

Apache-2.0. Individual source files retain their existing copyright notices.

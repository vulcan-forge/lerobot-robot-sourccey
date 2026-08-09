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
python -m pip install -e ".[hardware,record,dev]"
```

With `uv`, the equivalent command is:

```bash
uv pip install -e ".[hardware,record,dev]"
```

The `record` extra installs LeRobot's dataset and core-script dependencies
needed by commands such as `lerobot-record`. It is optional so arm-only and
robot-host installations do not have to carry the dataset stack.

## Registered device types

| Kind | LeRobot type | Python class |
| --- | --- | --- |
| Robot | `sourccey` | `Sourccey` |
| Robot | `sourccey_client` | `SourcceyClient` |
| Robot | `sourccey_follower` | `SourcceyFollower` |
| Teleoperator | `sourccey_leader` | `SourcceyLeader` |
| Teleoperator | `bi_sourccey_leader` | `BiSourcceyLeader` |
| Teleoperator | `sourccey_teleoperator` | `SourcceyTeleoperator` |

The distribution and import package are both named
`lerobot_robot_sourccey`. The `lerobot_robot_` prefix is intentional:
LeRobot scans installed top-level packages with this prefix and imports this
package, whose `__init__.py` registers all robot and teleoperator configs.

## Complete Sourccey teleoperation

`sourccey_teleoperator` combines both leader arms and keyboard base control
into one standard LeRobot teleoperator. It emits arm positions plus `x.vel`,
`y.vel`, `theta.vel`, and `z.vel`; no patched LeRobot teleoperation loop is
required.

Replace the serial ports with the ports reported by your system:

```bash
lerobot-teleoperate \
  --robot.type=sourccey_client \
  --robot.remote_ip=192.168.1.50 \
  --teleop.type=sourccey_teleoperator \
  --teleop.left_arm_port=/dev/ttyACM0 \
  --teleop.right_arm_port=/dev/ttyACM1
```

Keyboard defaults are W/S (forward/back), A/D (strafe), Z/X (rotate), Q/E
(Z actuator), R/F (speed), and N/M (toggle left/right arm torque).

Run the hardware host on Sourccey's Linux computer:

```bash
sourccey-host
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

## IMU and battery tools

Install the `hardware` extra on the robot host to enable Raspberry Pi GPIO,
the LSM6DSOX/LIS3MDL IMU, and BQ34Z100 I2C access:

```bash
uv pip install -e ".[hardware]"
```

Battery telemetry and diagnostics are installed as package commands:

```bash
sourccey-battery
sourccey-battery-check --pretty
sourccey-battery-configure info
sourccey-battery-configure setup-4s-lifepo4
```

Golden-image flashing is available through
`sourccey-battery-configure flash-golden` or `sourccey-battery-flash`.
These commands require direct I2C access to the BQ34Z100 and should first be
used with their dry-run or information modes.

## Validate the package

```bash
python -m pytest
python -m build
python -m pip install --force-reinstall --no-deps dist/*.whl
python -c "import lerobot_robot_sourccey"
```

The tests verify registration, stock-LeRobot config construction, composite
keyboard mapping, package-owned IMU/battery types, and Protobuf action
round-tripping.

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

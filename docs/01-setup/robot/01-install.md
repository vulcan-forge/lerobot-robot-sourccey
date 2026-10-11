# Install the robot

## Requirements

- Python 3.12 or 3.13
- LeRobot 0.6.x
- `uv`
- Linux with access to Sourccey's USB, GPIO, I2C, and camera devices

## Install a released package

```bash
uv pip install "lerobot-robot-sourccey[robot] @ git+https://github.com/vulcan-forge/lerobot-robot-sourccey.git@VERSION_TAG"
```

Replace `VERSION_TAG` with the release used by the controller computer.

For a PyPI release:

```bash
uv pip install "lerobot-robot-sourccey[robot]"
```

## Install from a source checkout

The setup script creates `.venv`, installs the robot profile, installs udev
aliases, and performs read-only hardware checks:

```bash
python setup/setup.py robot
```

Preview the setup without changing the environment or hardware:

```bash
python setup/setup.py robot --dry-run
```

After installation, the equivalent packaged command is:

```bash
uv run sourccey-setup robot
```

`sourccey-setup robot` is a provisioning command, not a package-installation
command. On Linux it installs packaged udev rules and performs read-only
battery checks. It never writes battery configuration unless
`--configure-battery` or `--flash-battery` is explicitly supplied. A
factory-prepared Sourccey does not need this command during normal updates.

## Install from `lerobot-vulcan`

From the `lerobot-vulcan` checkout on a factory-prepared robot computer:

```bash
uv sync --locked --extra sourccey-robot
```

This installs the locked robot-side dependencies. It does not change Linux
device rules, battery configuration, or hardware calibration.

Next, [start the robot host](05-host.md). If this is a fresh Linux computer or
the device aliases are missing, first [provision the robot devices](02-devices.md).

Return to the [robot setup index](README.md).

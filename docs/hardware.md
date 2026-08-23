# Hardware utilities

## Linux hardware dependencies

Install the `hardware` extra on the robot host to enable Raspberry Pi GPIO,
I2C, the LSM6DSOX/LIS3MDL IMU, and BQ34Z100 battery access:

```bash
python -m pip install -e ".[hardware]"
```

## Battery commands

The package installs these commands:

```bash
sourccey-battery
sourccey-battery-check --pretty
sourccey-battery-configure info
sourccey-battery-configure setup-4s-lifepo4
```

Golden-image flashing is available through
`sourccey-battery-configure flash-golden` or `sourccey-battery-flash`. These
commands require direct I2C access to the BQ34Z100. Start with their information
or dry-run modes before writing to the gauge.

See the [battery-specific guide](../src/lerobot_robot_sourccey/battery/README.md)
for configuration, diagnostics, and recovery details.

## Default robot devices

The complete robot expects these stable device links:

- Arms: `/dev/robotLeftArm` and `/dev/robotRightArm`
- Front cameras: `/dev/cameraFrontLeft` and `/dev/cameraFrontRight`
- Wrist cameras: `/dev/cameraWristLeft` and `/dev/cameraWristRight`

The active defaults are defined in
[`config_sourccey.py`](../src/lerobot_robot_sourccey/robots/sourccey/config_sourccey.py).

Return to the [documentation index](README.md).

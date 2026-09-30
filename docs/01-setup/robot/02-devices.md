# Verify robot devices

The robot setup command installs Sourccey's packaged udev rules, which provide
stable names for USB hardware even when Linux changes its `ttyUSB` or video
device numbers.

Run the installed setup command, then reconnect the USB devices:

```bash
uv run sourccey-setup robot
```

Verify the expected aliases:

```bash
ls -l /dev/robotLeftArm /dev/robotRightArm /dev/lidarFront
ls -l /dev/cameraWristLeft /dev/cameraWristRight
ls -l /dev/cameraFrontLeft /dev/cameraFrontRight /dev/cameraFrontBottom
```

The aliases should resolve to real `ttyUSB*` or `video*` devices. If an alias
is missing, inspect the connected hardware with `udevadm info`, confirm the USB
connection, and compare its physical port with
`src/lerobot_robot_sourccey/setup_data/99-sourccey-hardware.rules`.

The front LiDAR should normally appear as `/dev/lidarFront`. Validate its data
stream after installation with:

```bash
uv run sourccey-lidar-check
```

Next, inspect the [battery](03-battery.md), or return to the [robot setup
index](README.md).


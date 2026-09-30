# Sourccey 2D LiDAR

Sourccey's front range sensor is an LDROBOT LD19: a 360-degree, 2D LiDAR
connected through a CP2102 USB-to-serial adapter. The robot profile installs
`pyserial`, and the packaged udev rule exposes the sensor as `/dev/lidarFront`.

## Check the sensor

Run a three-second, read-only stream check on the robot:

```bash
uv run sourccey-lidar-check
```

The command validates packet CRCs and reports connectivity, rotation speed,
point counts, observed range, and data age. JSON output is available for
scripts and service checks:

```bash
uv run sourccey-lidar-check --duration 5 --json
```

The LD19 continuously transmits data, so this passive validation is its
equivalent of a ping. Do not run the check while another process owns the same
serial device.

## Open the live viewer

Start the dashboard on the robot:

```bash
uv run sourccey-lidar-view
```

The command prints its local URL, normally `http://127.0.0.1:8765`. To view it
securely from a development computer, open an SSH tunnel:

```bash
ssh -L 8765:127.0.0.1:8765 user@robot-ip
```

Then open `http://127.0.0.1:8765` on the development computer. Alternatively,
bind the viewer to the robot's LAN interface with `--host 0.0.0.0`; only do
this on a trusted network because the dashboard has no authentication.

The plot uses the LD19's native coordinate system: zero degrees is the
sensor's forward mark and angles increase clockwise. The triangle indicates
the robot's assumed forward direction.

## Read scans from Python

The parser and serial reader are usable independently of the dashboard:

```python
from lerobot_robot_sourccey.sensors.lidar import LD19Reader

with LD19Reader("/dev/lidarFront") as lidar:
    scan = lidar.read_scan(timeout_s=2.0)
    for point in scan.valid_points:
        print(point.angle_deg, point.distance_m, point.intensity)
```

See `examples/lidar_read_scan.py` for a runnable helper. Distances are metres,
intensities are raw 8-bit values, and scan angles are clockwise degrees from
the sensor's zero mark.

## Troubleshooting

- If `/dev/lidarFront` is absent, run `sourccey-setup robot` and reconnect the
  USB adapter, then inspect `/dev/ttyUSB*`.
- If the device is present but no scans arrive, verify that the LiDAR is
  spinning and that no other process has the serial port open.
- A growing CRC error rate usually indicates a baud-rate, USB, power, or cable
  problem. The LD19 default is 230400 baud.
- Override the device for direct testing with `--device /dev/ttyUSB0`.

Next, continue to [AI and datasets](../04-ai/README.md), or return to the
[SDK index](README.md).


# Sourccey Python SDK

The high-level API lives in `lerobot_robot_sourccey.sdk` and is exported from
the package root as `SourcceySDK`. It extends the standard LeRobot client, so
the low-level `get_observation()` and `send_action()` methods remain available.

```python
from lerobot_robot_sourccey import SourcceySDK

with SourcceySDK.from_ip("192.168.1.50") as robot:
    observation = robot.get_observation()
    frame = robot.get_camera("front_left", observation=observation)
    print(frame.shape)
```

## Helpers

| Helper | Purpose |
| --- | --- |
| `SourcceySDK.from_ip(ip)` | Build a configured SDK client |
| `available_cameras` | List configured camera names |
| `get_camera(name)` | Read one validated NumPy camera frame |
| `set_base_velocity(x=..., y=..., theta=...)` | Send all normalized base axes |
| `drive_for(..., duration_s=...)` | Refresh a timed base command and stop afterward |
| `stop_base()` | Explicitly stop all base axes |
| `set_lift_position(position)` | Set a normalized lift target from `-100` to `100` |

Base velocities use normalized values from `-1.0` to `1.0`; they are not yet
calibrated SI velocities. `set_base_velocity()` is a streamed command, so the
host watchdog stops the base unless the command is refreshed. Prefer
`drive_for()` for simple timed movement.

```python
with SourcceySDK.from_ip("192.168.1.50") as robot:
    robot.drive_for(x=0.2, duration_s=1.0)
    robot.set_lift_position(25.0)
```

`drive_for()` refreshes the command at 20 Hz by default and sends a stop in a
`finally` block. Keep the emergency stop accessible and clear the robot's path
before running any movement example.

## Examples

The example modules expose importable functions and runnable CLIs:

- `read_observation()` in `examples/sdk_read_observation.py`
- `capture_camera()` in `examples/sdk_camera.py`
- `drive_base()` in `examples/sdk_drive_base.py`

The robot host and SDK client must use releases with the same supported wire
protocol version. Incompatible clients fail during connection instead of
sending commands.

Next, [check and visualize the 2D LiDAR](02-lidar.md), or return to the
[SDK index](README.md).

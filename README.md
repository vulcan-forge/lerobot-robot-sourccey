# Sourccey for LeRobot

`lerobot_robot_sourccey` is a third-party LeRobot plugin for the Sourccey
robot and its leader-arm teleoperator. It works with LeRobot without requiring
Sourccey source files or patches inside the LeRobot repository.

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

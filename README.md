# Sourccey for LeRobot

`lerobot_robot_sourccey` is a third-party LeRobot plugin for the Sourccey
robot and its leader-arm teleoperator. It works with LeRobot without requiring
Sourccey source files or patches inside the LeRobot repository.

## Documentation

| Guide | Use it for |
| --- | --- |
| [Documentation index](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/README.md) | Browse all package documentation |
| [Setup](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/setup/README.md) | Install software, prepare hardware, calibrate, and start the host |
| [Control systems](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/control-systems/README.md) | Teleoperate, record, replay, and deploy policies |
| [AI and datasets](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/ai/README.md) | Manage datasets and train policies |

For the normal operating path, complete
[Setup](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/setup/README.md),
then follow
[Teleoperate](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/control-systems/teleoperate.md).

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
[Dataset tools](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/ai/datasets.md).

## Registered LeRobot types

| Kind | Type |
| --- | --- |
| Robot | `sourccey` |
| Robot | `sourccey_client` |
| Robot | `sourccey_follower` |
| Teleoperator | `sourccey_leader` |
| Teleoperator | `bi_sourccey_leader` |
| Teleoperator | `sourccey_teleoperator` |

LeRobot discovers the plugin from its `lerobot_robot_sourccey` distribution
and import-package name.

## License

Apache-2.0. Individual source files retain their existing copyright notices.

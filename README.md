# Sourccey for LeRobot

`lerobot_robot_sourccey` is a third-party LeRobot plugin for the Sourccey
robot and its leader-arm teleoperator. It works with LeRobot without requiring
Sourccey source files or patches inside the LeRobot repository.

## Documentation

| Guide | Use it for |
| --- | --- |
| [Documentation index](docs/README.md) | Browse all package documentation |
| [Setup](docs/setup.md) | Install the plugin and verify LeRobot discovery |
| [Controlling Sourccey](docs/control.md) | Start the host, calibrate, teleoperate, and troubleshoot |
| [Recording datasets](docs/recording.md) | Record demonstrations for training |
| [Hardware utilities](docs/hardware.md) | Battery, GPIO, I2C, IMU, and device information |
| [Development and distribution](docs/development.md) | Test, build, install, or publish the package |

For the normal operating path, complete [Setup](docs/setup.md), then follow
[Controlling Sourccey](docs/control.md).

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

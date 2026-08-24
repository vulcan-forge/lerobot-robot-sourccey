# Sourccey for LeRobot

`lerobot_robot_sourccey` is a third-party LeRobot plugin for the Sourccey
robot and its leader-arm teleoperator. It works with LeRobot without requiring
Sourccey source files or patches inside the LeRobot repository.

## Documentation

| Guide | Use it for |
| --- | --- |
| [Documentation index](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/README.md) | Browse all package documentation |
| [Setup](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/setup.md) | Install the plugin and verify LeRobot discovery |
| [Controlling Sourccey](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/control.md) | Start the host, calibrate, teleoperate, and troubleshoot |
| [Recording datasets](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/recording.md) | Record demonstrations for training |
| [Hardware utilities](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/hardware.md) | Battery, GPIO, I2C, IMU, and device information |
| [Development and distribution](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/development.md) | Test, build, install, or publish the package |

For the normal operating path, complete
[Setup](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/setup.md),
then follow
[Controlling Sourccey](https://github.com/vulcan-forge/lerobot-robot-sourccey/blob/main/docs/control.md).

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

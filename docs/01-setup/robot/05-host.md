# Start the robot host

The host runs on Sourccey's Linux computer and exposes the robot to a
`sourccey_client` on the controller computer.

Start it after installing the robot profile. Device provisioning and
calibration are only required when setting up a fresh computer or recovering
serviced hardware:

```bash
uv run sourccey-host
```

Leave this process running while teleoperating, recording, replaying, or
deploying a policy. The robot and controller must be on the same network, and
the controller's `--robot.remote_ip` must point to the robot computer.

Stop the host before changing battery configuration, flashing the battery
gauge, or running any robot calibration command.

Next, follow [Teleoperate](../../02-control-systems/01-teleoperate.md), or return to the
[setup index](README.md).

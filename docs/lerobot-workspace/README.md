# Get started with Sourccey

This folder is the one-stop path for using Sourccey from a
`lerobot-vulcan` checkout. It intentionally repeats the normal operating flow
from the
[`lerobot-robot-sourccey` documentation](../README.md)
so you do not need to switch repositories while getting started.

## The two-computer setup

| Computer            | Connected to                                      | Runs                                  |
| ------------------- | ------------------------------------------------- | ------------------------------------- |
| Robot computer      | Sourccey's arms, base, lift, cameras, and sensors | `sourccey-host`                       |
| Controller computer | Leader arms and optional training GPU             | LeRobot commands from this repository |

Both computers must be on the same network. Run every controller command from
the root of the `lerobot-vulcan` checkout unless a guide says otherwise.

## Start here

Follow these guides in order. Do not move to the next guide until its check
passes.

1. [Set up both computers](01-setup.md) — install the correct package profiles,
   prepare the leader arms, and start the host.
2. [Teleoperate](02-teleoperate.md) — prove that the network, leader arms, robot,
   keyboard, and cameras work together.
3. [Record](03-record.md) — collect a small demonstration dataset.
4. [Replay](04-replay.md) — validate the recorded actions on the robot.
5. [Train](05-train.md) — train an ACT policy from the dataset.
6. [Roll out](06-rollout.md) — run the trained policy for a short, supervised test.

If a check fails, use [Troubleshooting](troubleshooting.md) before continuing.

## How commands are written

Each code block contains exactly one command. Long LeRobot commands remain one
command even when they wrap visually in your editor. Example values used
throughout the guides are:

| Setting          | Example                         | Replace with                                 |
| ---------------- | ------------------------------- | -------------------------------------------- |
| Robot IP         | `192.168.1.243`                 | The robot computer's IP address              |
| Left leader arm  | `COM5`                          | The detected left leader-arm port            |
| Right leader arm | `COM6`                          | The detected right leader-arm port           |
| Dataset          | `vulcan-studio/sourccey-demo-1` | Your Hugging Face namespace and dataset name |
| Task             | `Fold the shirt`                | One short, consistent task instruction       |

Commands are shown on one line so they work in PowerShell, Command Prompt,
Git Bash, and POSIX shells. Replace example values before running a command;
do not type placeholder brackets such as `<ROBOT_IP>` into a shell.

## Safety

- Keep the robot's full workspace clear before any command that can move it.
- Keep an emergency stop within reach.
- Start with short recordings and rollouts.
- Stop `sourccey-host` before robot calibration or direct hardware checks.
- Run `sourccey-host` only on the robot computer.

For package development, device internals, and battery maintenance, use the
[full Sourccey package documentation](../README.md).

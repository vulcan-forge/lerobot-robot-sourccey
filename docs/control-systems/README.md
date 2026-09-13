# Control systems

These guides cover manual control, data collection, action replay, and policy
deployment. Run the commands from the `lerobot-vulcan` checkout on the
controller computer unless a guide says otherwise.

1. [Teleoperate](teleoperate.md) — manually control Sourccey without saving data.
2. [Record](record.md) — collect teleoperated demonstrations.
3. [Replay](replay.md) — replay a recorded episode on Sourccey.
4. [Rollout](rollout.md) — deploy a trained policy on Sourccey.

Dataset tooling and policy training are documented under
[AI and datasets](../ai/README.md).

Start `sourccey-host` on the robot before running teleoperate, record, replay,
or rollout:

```bash
uv run sourccey-host
```

Replace example IP addresses, serial ports, dataset IDs, and model paths with
values for the current robot and task.

Return to the [documentation index](../README.md).

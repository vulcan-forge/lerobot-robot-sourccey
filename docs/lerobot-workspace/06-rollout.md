# Roll out a trained policy

A rollout gives the policy direct control of Sourccey. Start with 30 seconds,
clear the full workspace, keep an emergency stop within reach, and supervise
the entire run.

Start `sourccey-host` on the robot computer, then run this on the controller:

```bash
uv run --no-sync sourccey-rollout --strategy.type=base --policy.path=outputs/train/act-sourccey-demo-1/checkpoints/last/pretrained_model --robot.type=sourccey_client --robot.id=sourccey --robot.remote_ip=192.168.1.243 --task="Fold the shirt" --duration=30 --fps=30 --device=cuda --display_data=true
```

Install the Sourccey package's `desktop` profile against this LeRobot checkout.
The package command uses LeRobot's rollout strategies and supports the desktop
stop-file setting `--shutdown_event_path`. Standard `lerobot-rollout` remains
available without stop-file control.

An unavailable follower arm still publishes missing measurements. Policy rollout
requires explicitly configured placeholder poses for a policy intended to operate
without that arm. See the package's
[rollout guide](../rollout.md)
for `robot.missing_arm_positions`, joint units, and command suppression.

The task text and the policy's observation and action features must match the
training dataset, including camera names and the `z.pos` action. Use `mps` or
`cpu` instead of `cuda` when appropriate for the controller.

## Check before extending the rollout

Confirm that the robot responds smoothly, remains inside the expected
workspace, stops at 30 seconds, and does not produce feature-shape or camera
errors. Increase `--duration` only after repeated short rollouts behave safely.

Previous: [Train](05-train.md). Return to the [Sourccey guide](README.md).

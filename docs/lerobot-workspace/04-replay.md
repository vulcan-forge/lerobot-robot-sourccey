# Replay a recorded episode

Replay sends the actions from a recorded episode back to Sourccey. It can move
the arms, base, and lift without leader-arm input.

Before starting, clear the workspace, keep an emergency stop within reach,
and confirm that `sourccey-host` is running. Then run this on the controller:

```bash
uv run lerobot-replay --robot.type=sourccey_client --robot.id=sourccey --robot.remote_ip=192.168.1.243 --dataset.repo_id=vulcan-studio/sourccey-demo-1 --dataset.episode=0
```

If you installed the Sourccey plugin as an editable checkout, change the
beginning to `uv run --no-sync lerobot-replay`.

Episode numbers are zero-based, so `0` is the first episode. The robot
configuration and workspace must match the recording setup.

## Check before continuing

Watch the entire episode. The action sequence should be smooth and recognizable,
and the robot should stop when replay finishes. Do not train on the dataset if
replay reveals an incorrect feature mapping, unexpected lift behavior, or
unsafe motion.

Next: [Train](05-train.md).

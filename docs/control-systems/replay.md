# Replay

Replay sends the recorded actions from one dataset episode back to Sourccey.
Clear the workspace and be ready to stop the robot before starting.

```bash
uv run --no-sync lerobot-replay \
  --robot.type=sourccey_client \
  --robot.id=sourccey \
  --robot.remote_ip=192.168.1.243 \
  --dataset.repo_id=vulcan-studio/sourccey-demo-1 \
  --dataset.episode=0
```

The robot configuration must match the hardware used during recording. Episode
numbers are zero-based, so `0` selects the first episode.

Next, [train a policy](../ai/train.md), or return to the
[control-systems index](README.md).

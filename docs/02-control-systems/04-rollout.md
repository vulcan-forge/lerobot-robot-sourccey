# Rollout

Rollout deploys a trained policy on Sourccey. Start with a short duration in a
clear workspace and keep an emergency stop within reach.

```bash
uv run --no-sync lerobot-rollout \
  --strategy.type=base \
  --policy.path=outputs/train/act-sourccey-demo-1/checkpoints/last/pretrained_model \
  --robot.type=sourccey_client \
  --robot.id=sourccey \
  --robot.remote_ip=192.168.1.243 \
  --task="Fold the shirt" \
  --duration=30 \
  --fps=30 \
  --device=cuda \
  --display_data=true
```

The policy's observation and action features must match the dataset used for
training, including camera names and the `z.pos` action. Increase
`--duration` only after confirming that the short rollout behaves safely.

Return to the [control-systems index](README.md).

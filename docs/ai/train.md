# Train

Training does not connect to the robot. Run it on a computer with the dataset
available locally or on the Hugging Face Hub.

```bash
uv run lerobot-train \
  --dataset.repo_id=vulcan-studio/sourccey-demo-1 \
  --policy.type=act \
  --policy.device=cuda \
  --output_dir=outputs/train/act-sourccey-demo-1 \
  --job_name=act-sourccey-demo-1 \
  --batch_size=8 \
  --steps=20000 \
  --save_freq=5000 \
  --wandb.enable=false \
  --policy.push_to_hub=false
```

Use `cuda` for a supported NVIDIA GPU, `mps` for Apple silicon, or `cpu`
for a CPU-only run. Adjust batch size if training runs out of device memory.
The trained checkpoints are written beneath `--output_dir`.

Next, [deploy the trained policy](../control-systems/rollout.md), or return to
the [AI index](README.md).

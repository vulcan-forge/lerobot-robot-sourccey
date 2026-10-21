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

Next, [deploy the trained policy](../02-control-systems/04-rollout.md), or return to
the [AI index](README.md).


## Automatic retry

The Sourccey package provides a wrapper that retries upstream LeRobot training
from the last saved checkpoint after a failed run. Install its training extra
from the LeRobot workspace:

```bash
uv pip install -e "../packages/lerobot-robot-sourccey[training]"
```

Pass the normal `lerobot-train` arguments after the retry options:

```bash
uv run --no-sync sourccey-train-retry --max-attempts=3 --retry-delay-seconds=20 --dataset.repo_id=vulcan-studio/sourccey-demo-1 --policy.type=act --policy.device=cuda --output_dir=outputs/train/act-sourccey-demo-1 --steps=20000 --policy.push_to_hub=false
```

The wrapper stops if no resumable checkpoint exists. On retry it uses
`checkpoints/last/pretrained_model/train_config.json` and drops the initial
`--policy.path` argument so upstream's resume handling can load that checkpoint.
`lerobot-train-retry` remains available as a compatibility alias provided by
the Sourccey package. The training implementation stays in LeRobot.

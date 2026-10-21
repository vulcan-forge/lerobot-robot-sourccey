# Train a Sourccey policy

Training does not connect to the robot, so `sourccey-host` is not required.
Run training on the controller or another computer that can access the
dataset.

This first run trains an ACT policy for 20,000 steps:

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

Use `cuda` for a supported NVIDIA GPU, `mps` for Apple silicon, or `cpu` for a
CPU-only run. Lower `--batch_size` if the device runs out of memory.

## Check before continuing

Training should produce checkpoints beneath:

```text
outputs/train/act-sourccey-demo-1/checkpoints/
```

Continue only after the `last/pretrained_model` directory exists and training
completed without a dataset feature or video-decoding error.

## Higher-capacity option: X-VLA

If the training computer has a stronger NVIDIA GPU with sufficient VRAM, we
recommend fine-tuning the 0.9B-parameter X-VLA base model as the
higher-capacity option. Install its dependencies first:

```bash
uv sync --locked --extra sourccey-desktop --extra training --extra xvla
```

Then train from the pretrained base checkpoint:

```bash
uv run lerobot-train \
  --dataset.repo_id=vulcan-studio/sourccey-demo-1 \
  --output_dir=outputs/train/xvla-sourccey-demo-1 \
  --job_name=xvla-sourccey-demo-1 \
  --policy.path=lerobot/xvla-base \
  --policy.dtype=bfloat16 \
  --policy.action_mode=auto \
  --policy.device=cuda \
  --policy.freeze_vision_encoder=false \
  --policy.freeze_language_encoder=false \
  --policy.train_policy_transformer=true \
  --policy.train_soft_prompts=true \
  --steps=20000 \
  --policy.push_to_hub=false
```

X-VLA uses `bfloat16` to reduce memory use. If training runs out of memory,
reduce the batch size before changing the model configuration.

For larger datasets, cleanup, and video audits, see the package's
[dataset guide](../04-ai/01-datasets.md).

Next: [Roll out](06-rollout.md).

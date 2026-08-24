# Sourccey folding tasks

> Status: Internal runbook

```
-------
Fold the shirt
Grab a shirt from the pile
Place the folded shirt to the side
Grab a shirt from the pile, fold it, then place the folded shirt to the side.

-------
```

```
uv run -m lerobot.robots.sourccey.sourccey.sourccey.sourccey_host
```

```
uv run lerobot-teleoperate \
 --robot.type=sourccey_client \
 --robot.id="sourccey" \
 --robot.remote_ip="192.168.1.243" \
 --teleop.type=bi_sourccey_leader \
 --teleop.id="sourccey_leader" \
 --teleop.left_arm_port="/dev/ttyACM0" \
 --teleop.right_arm_port="/dev/ttyACM1" \
 --teleop_keyboard.type=keyboard \
 --teleop_keyboard.id="sourccey_keyboard" \
 --fps=30 \
 --display_data=true
```

```
uv run lerobot-record \
 --robot.type=sourccey_client \
 --robot.id="sourccey" \
 --robot.remote_ip="192.168.1.212" \
 --teleop.type=bi_sourccey_leader \
 --teleop.id="sourccey_leader" \
 --teleop.left_arm_port="/dev/ttyACM0" \
 --teleop.right_arm_port="/dev/ttyACM1" \
 --teleop_keyboard.type=keyboard \
 --teleop_keyboard.id="sourccey_keyboard" \
 --dataset.repo_id="sourccey-013/nickm/sourccey-013__pile-shirt-fold-a/sourccey-013__shirt-fold__green__set041__nickm" \
 --dataset.num_episodes=5 \
 --dataset.episode_time_s=300 \
 --dataset.reset_time_s=15 \
 --dataset.single_task="Fold the shirt" \
 --dataset.fps=30 \
 --display_data=true \
 --dataset.push_to_hub=false
```

```
uv run lerobot-rollout \
  --strategy.type=sentry \
  --policy.path="outputs/train/xvla_s_sourccey-shirt-fold-c-0012/checkpoints/0640000/pretrained_model" \
  --robot.type=sourccey_client \
  --robot.id="sourccey" \
  --robot.remote_ip="192.168.1.212" \
  --dataset.repo_id="sourccey-013/rollout_sourccey-013__shirt-fold-blue-c/xvla_s_sourccey-shirt-fold-c-000" \
  --dataset.single_task="Fold the shirt" \
  --dataset.push_to_hub=false \
  --duration=600 \
  --fps=30 \
  --device=cuda
```

# Training commands with retry

```
/home/sourccey/.cache/huggingface/lerobot/Combination/sourccey-shirt-fold-c-008
```

```
CUDA_VISIBLE_DEVICES=1 python src/lerobot/scripts/lerobot_train_retry.py \
  --max-attempts=30 \
  --retry-delay-seconds=20 \
  --dataset.repo_id="Combination/sourccey-shirt-fold-c-009" \
  --output_dir="outputs/train/xvla_s_sourccey-shirt-fold-c-009" \
  --job_name="xvla_s_sourccey-shirt-fold-c-009" \
  --policy.path="lerobot/xvla-base" \
  --policy.dtype=bfloat16 \
  --policy.action_mode=auto \
  --policy.max_action_dim=20 \
  --policy.device=cuda \
  --policy.push_to_hub=false \
  --policy.input_features=null \
  --policy.scheduler_warmup_steps=5000 \
  --policy.scheduler_decay_steps=1000000 \
  --policy.scheduler_decay_lr=5e-06 \
  --steps=1000000 \
  --save_freq=200 \
  --batch_size=8 \
  --wandb.enable=false
```

#Fine tune

```
CUDA_VISIBLE_DEVICES=1 uv run lerobot-train-retry \
  --max-attempts=30 \
  --retry-delay-seconds=20 \
  --dataset.repo_id="Combination/sourccey-shorts-fold-c-000" \
  --output_dir="outputs/train/xvla_s_sourccey-shorts-fold-c-000" \
  --job_name="xvla_s_sourccey-shorts-fold-c-000" \
  --policy.path="outputs/train/xvla_s_sourccey-shirt-fold-c-009/checkpoints/1000000/pretrained_model" \
  --policy.dtype=bfloat16 \
  --policy.action_mode=auto \
  --policy.max_action_dim=20 \
  --policy.device=cuda \
  --policy.push_to_hub=false \
  --policy.input_features=null \
  --policy.scheduler_warmup_steps=10000 \
  --policy.scheduler_decay_steps=1000000 \
  --policy.scheduler_decay_lr=5e-06 \
  --steps=1000000 \
  --save_freq=50000 \
  --batch_size=8 \
  --wandb.enable=false
```

#Cache Fine tune

```
CUDA_VISIBLE_DEVICES=1 uv run lerobot-train-retry \
  --max-attempts=30 \
  --retry-delay-seconds=20 \
  --dataset.repo_id="Combination/sourccey-shirt-fold-c-010" \
  --dataset.image_transforms.enable=false \
  --dataset.streaming=false \
  --output_dir="outputs/train/xvla_s_sourccey-shirt-fold-c-010" \
  --job_name="xvla_s_sourccey-shirt-fold-c-010" \
  --policy.path="outputs/sft/xvla_s_sourccey-shirt-fold-c-010-pre-000/checkpoints/500000/pretrained_model" \
  --policy.dtype=bfloat16 \
  --policy.action_mode=auto \
  --policy.max_action_dim=20 \
  --policy.device=cuda \
  --policy.push_to_hub=false \
  --policy.input_features=null \
  --policy.freeze_vision_encoder=true \
  --policy.freeze_language_encoder=true \
  --policy.cache_florence_features=true \
  --policy.florence_cache_path="outputs/cache/florence/sourccey-shirt-fold-c-010-500000.sqlite" \
  --policy.scheduler_warmup_steps=10000 \
  --policy.scheduler_decay_steps=500000 \
  --policy.scheduler_decay_lr=5e-06 \
  --steps=500000 \
  --save_freq=100000 \
  --batch_size=8 \
  --wandb.enable=false
```

# Resume

CUDA_VISIBLE_DEVICES=1 uv run lerobot-train-retry \
 --max-attempts=30 \
 --retry-delay-seconds=20 \
 --output_dir="outputs/train/xvla_light_sourccey-shirt-fold-c-009" \
 --resume=true \
 --config_path="outputs/train/xvla_light_sourccey-shirt-fold-c-009/checkpoints/last/pretrained_model/train_config.json"

# Resume Cache

CUDA_VISIBLE_DEVICES=0 uv run lerobot-train-retry \
 --max-attempts=30 \
 --retry-delay-seconds=20 \
 --output_dir="outputs/train/xvla_light_sourccey-shirt-fold-c-009-cached" \
 --resume=true \
 --config_path="outputs/train/xvla_light_sourccey-shirt-fold-c-009-cached/checkpoints/last/pretrained_model/train_config.json"

```
CUDA_VISIBLE_DEVICES=1 uv run lerobot-train-retry \
  --max-attempts=30 \
  --retry-delay-seconds=20 \
  --output_dir="outputs/train/xvla_s_sourccey-shirt-fold-c-008" \
  --steps=1000000 \
  --save_freq=20000 \
  --resume=true \
  --config_path="outputs/train/xvla_s_sourccey-shirt-fold-c-008/checkpoints/last/pretrained_model/train_config.json"

```

## SARM

```
CUDA_VISIBLE_DEVICES=1 uv run lerobot-train \
 --dataset.repo_id="Combination/sourccey-shirt-fold-01**cmbF**d**chrism**20260407**append**20260408" \
 --reward_model.type=sarm \
 --reward_model.annotation_mode=single_stage \
 --reward_model.image_keys='["observation.images.front_right","observation.images.front_left"]' \
 --output_dir=outputs/train/sarm_2cam \
 --batch_size=8 \
 --steps=20000 \
 --wandb.enable=false \
 --reward_model.push_to_hub=false
```

# Convert model architecture:

```
uv run lerobot-convert-xvla-light \
  --source="outputs/train/xvla_s_sourccey-shirt-fold-c-009/checkpoints/1000000/pretrained_model" \
  --output-dir="outputs/converted/xvla-light-sourccey-shirt-fold-c-009"
```

# Convert XVLA-light to XVLA-extra-light (512 hidden size, 8 heads)

XVLA-extra-light inherits XVLA-light and XVLA, including Florence, action processing, rollout behavior,
and the optional Florence cache. Its converter keeps complete 64-dimensional attention heads while
reducing the policy-transformer residual stream from 1024 to 512.

```
uv run lerobot-convert-xvla-extra-light \
  --source="outputs/converted/xvla-light-sourccey-shirt-fold-c-009/checkpoints/1000000/pretrained_model" \
  --output-dir="outputs/converted/xvla-extra-light-sourccey-shirt-fold-c-009"
```

Train it using the converted output as `--policy.path`. Since Florence and preprocessing are unchanged,
it can reuse the same Florence cache database created by XVLA-light.

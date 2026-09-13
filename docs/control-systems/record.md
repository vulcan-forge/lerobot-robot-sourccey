# Record

Confirm that [teleoperation](teleoperate.md) works before collecting
demonstrations.

```bash
uv run --no-sync lerobot-record \
  --robot.type=sourccey_client \
  --robot.id=sourccey \
  --robot.remote_ip=192.168.1.243 \
  --teleop.type=bi_sourccey_leader \
  --teleop.id=sourccey_leader \
  --teleop.left_arm_port=COM5 \
  --teleop.right_arm_port=COM6 \
  --teleop_keyboard.type=keyboard \
  --teleop_keyboard.id=sourccey_keyboard \
  --dataset.repo_id=vulcan-studio/sourccey-demo-1 \
  --dataset.num_episodes=5 \
  --dataset.episode_time_s=300 \
  --dataset.reset_time_s=15 \
  --dataset.single_task="Fold the shirt" \
  --dataset.fps=30 \
  --dataset.push_to_hub=false \
  --display_data=true
```

During recording, Right Arrow saves the current episode, Left Arrow discards
and re-records it, and Escape stops recording. Keep
`--dataset.push_to_hub=false` for a local dataset; set it to `true` when the
finished dataset should be uploaded.

The split keyboard path converts Q/E input into an absolute `z.pos` target
using the latest robot observation.

Next, [replay an episode](replay.md), or return to the
[control-systems index](README.md).

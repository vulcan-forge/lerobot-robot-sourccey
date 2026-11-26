# Record

Confirm that [teleoperation](01-teleoperate.md) works before collecting
demonstrations.

```bash
uv run --no-sync lerobot-record \
  --robot.type=sourccey_client \
  --robot.id=sourccey \
  --robot.remote_ip=192.168.1.243 \
  --teleop.type=composite \
  --teleop.base.type=keyboard \
  --teleop.arm.type=bi_sourccey_leader \
  --teleop.arm.id=sourccey_leader \
  --teleop.arm.left_arm_port=COM5 \
  --teleop.arm.right_arm_port=COM6 \
  --teleop.mapping.type=sourccey_keyboard \
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

The keyboard mapping turns the lift keys into an absolute `z.pos` target that
starts at the measured lift position, so recorded actions keep the same
features as before. Movement keys take priority over recording shortcuts with
the same key: on AZERTY, `Q` moves left instead of stopping the recording.

Next, [replay an episode](03-replay.md), or return to the
[control-systems index](README.md).

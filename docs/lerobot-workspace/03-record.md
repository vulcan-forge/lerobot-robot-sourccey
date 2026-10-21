# Record a Sourccey dataset

Record only after [teleoperation](02-teleoperate.md) passes. Start with five short
episodes so mistakes are inexpensive to correct.

On the controller computer, replace the IP address, leader-arm ports, dataset
ID, and task, then run:

```bash
uv run sourccey-record --robot.type=sourccey_client --robot.id=sourccey --robot.remote_ip=192.168.1.243 --teleop.type=sourccey_teleoperator --teleop.id=sourccey_leader --teleop.left_arm_port=COM5 --teleop.right_arm_port=COM6 --dataset.repo_id=vulcan-studio/sourccey-demo-1 --dataset.num_episodes=5 --dataset.episode_time_s=60 --dataset.reset_time_s=15 --dataset.single_task="Fold the shirt" --dataset.fps=30 --dataset.push_to_hub=false --display_data=true
```

If you installed the Sourccey plugin as an editable checkout, change the
beginning to `uv run --no-sync sourccey-record`.

## Recording controls

| Key         | Result                                    |
| ----------- | ----------------------------------------- |
| Right Arrow | Save the current episode                  |
| Left Arrow  | Discard and re-record the current episode |
| Escape      | Stop recording                            |

Keep `--dataset.push_to_hub=false` for a local dataset. Change it to `true`
only when you intend to upload the completed dataset and are logged in to the
correct Hugging Face account.

## Check before continuing

Recordings should use the same task wording, camera placement, starting area,
and success condition. Discard an episode when control is interrupted, the
task fails, or a camera freezes.

The recording is ready for the next step when all five episodes save without
a camera, timing, or serialization error.

Next: [Replay](04-replay.md).

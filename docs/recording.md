# Recording datasets

Confirm that [manual control](control.md) works before recording. Use the same
robot IP and leader-arm ports with LeRobot's recording command.

## Windows example

```powershell
cd C:\Users\Nicholas\Desktop\Projects\Vulcan\lerobot-vulcan
uv run --no-sync lerobot-record `
  --robot.type=sourccey_client `
  --robot.id=sourccey `
  --robot.remote_ip=192.168.1.50 `
  --teleop.type=sourccey_teleoperator `
  --teleop.id=sourccey_leader `
  --teleop.left_arm_port=COM5 `
  --teleop.right_arm_port=COM6 `
  --dataset.repo_id=YOUR_HF_USERNAME/sourccey-demo `
  --dataset.num_episodes=5 `
  --dataset.episode_time_s=300 `
  --dataset.reset_time_s=15 `
  --dataset.single_task="Fold the shirt" `
  --dataset.fps=30 `
  --dataset.push_to_hub=false `
  --display_data=true
```

Change the task, episode length, reset time, and repository ID for the
demonstration being collected. Keep `--dataset.push_to_hub=false` for local
recording; set it to `true` only when the dataset should be uploaded.

## Important parameters

| Parameter | Purpose |
| --- | --- |
| `--dataset.repo_id` | Dataset name and Hugging Face namespace |
| `--dataset.num_episodes` | Number of demonstrations to collect |
| `--dataset.episode_time_s` | Maximum duration of each demonstration |
| `--dataset.reset_time_s` | Time allowed to reset between demonstrations |
| `--dataset.single_task` | Natural-language description of the task |
| `--dataset.fps` | Dataset and control frequency |
| `--dataset.push_to_hub` | Whether to upload after recording |

Return to the [documentation index](README.md).

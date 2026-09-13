# Teleoperate

Use teleoperation to verify the robot connection, leader arms, keyboard
controls, and cameras before recording a dataset.

```bash
uv run --no-sync lerobot-teleoperate \
  --robot.type=sourccey_client \
  --robot.id=sourccey \
  --robot.remote_ip=192.168.1.243 \
  --teleop.type=bi_sourccey_leader \
  --teleop.id=sourccey_leader \
  --teleop.left_arm_port=COM5 \
  --teleop.right_arm_port=COM6 \
  --teleop_keyboard.type=keyboard \
  --teleop_keyboard.id=sourccey_keyboard \
  --fps=30 \
  --display_data=true
```

Keyboard controls:

| Keys | Action |
| --- | --- |
| `W` / `S` | Move forward / backward |
| `A` / `D` | Move left / right |
| `Z` / `X` | Rotate left / right |
| `Q` / `E` | Raise / lower the Z position target |
| `R` / `F` | Increase / decrease base speed |
| `N` / `M` | Toggle left / right arm untorque |

Use `--no-sync` while testing a locally editable Sourccey package. Omit it
after `lerobot-vulcan` is pinned to the required package release.

Next, [record a dataset](record.md), or return to the
[control-systems index](README.md).

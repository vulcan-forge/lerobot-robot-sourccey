# Teleoperate

Use teleoperation to verify the robot connection, leader arms, keyboard
controls, and cameras before recording a dataset.

```bash
uv run --no-sync lerobot-teleoperate \
  --robot.type=sourccey_client \
  --robot.id=sourccey \
  --robot.remote_ip=192.168.1.230 \
  --teleop.type=composite \
  --teleop.base.type=keyboard \
  --teleop.arm.type=bi_sourccey_leader \
  --teleop.arm.id=sourccey_leader \
  --teleop.arm.left_arm_port=COM14 \
  --teleop.arm.right_arm_port=COM13 \
  --teleop.mapping.type=sourccey_keyboard \
  --fps=30 \
  --display_data=true
```

The composite teleoperator combines the keyboard (base, lift, and untorque
toggles) with the leader arms. Omit the `--teleop.arm.*` options to drive with
the keyboard alone; the follower arms then hold their measured position.

Keyboard controls, by physical key position. Add
`--teleop.mapping.layout=azerty` or `--teleop.mapping.layout=qwertz` for those
keyboards:

| QWERTY    | AZERTY    | Action                              |
| --------- | --------- | ----------------------------------- |
| `W` / `S` | `Z` / `S` | Move forward / backward             |
| `A` / `D` | `Q` / `D` | Move left / right                   |
| `Z` / `X` | `W` / `X` | Rotate left / right                 |
| `Q` / `E` | `A` / `E` | Raise / lower the Z position target |
| `+` / `-` | `+` / `-` | Increase / decrease base speed      |
| `N` / `M` | `N` / `,` | Toggle left / right arm untorque    |

Base speeds are normalized wheel commands. Change the three presets with
`--teleop.mapping.linear_speeds='[0.8,0.9,1.0]'` and
`--teleop.mapping.angular_speeds='[0.8,0.9,1.0]'`.

On macOS, allow the terminal application under System Settings → Privacy &
Security → Accessibility so the keyboard listener receives key presses.

Use `--no-sync` while testing a locally editable Sourccey package. Omit it
after `lerobot-vulcan` is pinned to the required package release.

Next, [record a dataset](02-record.md), or return to the
[control-systems index](README.md).

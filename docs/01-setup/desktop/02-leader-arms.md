# Leader-arm ports

The controller computer connects directly to the left and right leader arms.
Identify both serial ports before teleoperating.

On Linux:

```bash
uv run lerobot-find-port
```

Stable Linux aliases may also be configured as:

```text
/dev/robotLeftArm
/dev/robotRightArm
```

In Git Bash on Windows, use the Windows serial names directly:

```bash
LEFT_ARM_PORT=COM14
RIGHT_ARM_PORT=COM13
```

Pass them to control commands with:

```bash
--teleop.left_arm_port="$LEFT_ARM_PORT" \
--teleop.right_arm_port="$RIGHT_ARM_PORT"
```

## Calibrate the leader arms

Automatically calibrate both leader arms from the packaged Sourccey homing
positions and motion ranges:

```bash
uv run sourccey-teleop-calibrate \
  --left-arm-port="$LEFT_ARM_PORT" \
  --right-arm-port="$RIGHT_ARM_PORT"
```

To calibrate only one leader arm:

```bash
uv run sourccey-teleop-calibrate --arm left --left-arm-port="$LEFT_ARM_PORT"
uv run sourccey-teleop-calibrate --arm right --right-arm-port="$RIGHT_ARM_PORT"
```

On Linux, the command defaults to `/dev/robotLeftArm` and
`/dev/robotRightArm`, so the port arguments can be omitted when those stable
aliases are configured.

If an arm cannot connect, confirm the selected port, USB connection, motor
power, and that no other process has the serial port open.

Next, follow [Teleoperate](../../02-control-systems/01-teleoperate.md).

Return to the [desktop setup index](README.md).

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
LEFT_ARM_PORT=COM5
RIGHT_ARM_PORT=COM6
```

Pass them to control commands with:

```bash
--teleop.left_arm_port="$LEFT_ARM_PORT" \
--teleop.right_arm_port="$RIGHT_ARM_PORT"
```

If an arm cannot connect, confirm the selected port, USB connection, motor
power, and that no other process has the serial port open.

Next, follow [Teleoperate](../../control-systems/teleoperate.md).

Return to the [desktop setup index](README.md).

# Calibrate Sourccey

Calibration is not part of a normal software update on a factory-prepared
Sourccey. Use it after replacing an arm, changing motor configuration, losing
calibration files, or servicing the Z actuator.

Run calibration on the robot computer with `sourccey-host` stopped. The default
soft calibration applies the packaged follower-arm ranges and preserves the
current Z limits. No special arm pose is required, and soft calibration does
not seek the physical Z endpoints:

```bash
uv run sourccey-calibrate
```

To redetect physical arm limits and both Z endpoints, clear people and
obstacles from the robot's full workspace, keep the emergency stop within
reach, and explicitly acknowledge the movement:

```bash
uv run sourccey-calibrate --full-reset --yes
```

One arm can be calibrated without connecting the other arm, base, or Z
actuator:

```bash
uv run sourccey-calibrate --arm left
uv run sourccey-calibrate --arm right --full-reset --yes
```

Use `--left-arm-port`, `--right-arm-port`, `--id`, or
`--calibration-dir` to override their configured values.

Next, [start the robot host](05-host.md), or return to the [robot setup
index](README.md).

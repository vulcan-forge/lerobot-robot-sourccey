# Calibrate Sourccey

Run calibration on the robot computer with `sourccey-host` stopped. Soft
auto-calibration applies the packaged arm ranges and saves the current Z sensor
limits without moving Z:

```bash
uv run sourccey-calibrate
```

To redetect the physical arm limits and both Z endpoints, clear people and
obstacles from the robot's full workspace, then acknowledge the movement:

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

Next, [start the robot host](host.md), or return to the [robot setup
index](README.md).

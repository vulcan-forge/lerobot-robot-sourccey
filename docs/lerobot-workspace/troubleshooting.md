# Troubleshoot Sourccey

Work from the top of the relevant section and run one command at a time.

## Plugin does not load

Reinstall the locked controller environment:

```bash
uv sync --locked --extra sourccey-desktop --extra training
```

Check the installed plugin version:

```bash
uv run python -c "import importlib.metadata as m; print(m.version('lerobot-robot-sourccey'))"
```

If you intentionally use an editable package checkout, add `--no-sync` after
`uv run` in control commands so `uv` does not replace it with the locked
version.

## Controller cannot reach the robot

Confirm that the example IP was replaced and test the robot address:

```bash
ping 192.168.1.243
```

Confirm that `uv run sourccey-host` is still running on the robot computer. A
`no observation packet` message usually means the host is stopped, the IP is
wrong, or the two computers are on different networks.

## A leader arm cannot connect

Disconnect one leader arm and find the remaining port:

```bash
uv run lerobot-find-port
```

Check the selected port, USB connection, motor power, and whether another
process already has the serial port open. Repeat with the other arm.

## Cameras or robot hardware fail

With `sourccey-host` running, check the eye cameras from the controller:

```bash
uv run --no-sync sourccey-check-eye-cameras --remote-ip 192.168.1.243 --skip-bottom
```

Check the wrist cameras:

```bash
uv run --no-sync sourccey-check-arm-cameras --remote-ip 192.168.1.243
```

Stop `sourccey-host` before direct device checks on the robot computer. The
complete camera, motor, lift, LiDAR, IMU, and battery procedures are in the
[Sourccey hardware checks](./hardware-checks.mdx).

## Right shoulder suddenly flips near startup

Stop inference and `sourccey-host`. If the right `shoulder_lift` started near a
raw encoder rollover and then commanded a large, implausible movement, follow
the [right shoulder encoder-seam diagnosis and fix](right-shoulder-encoder-seam.md).
Preserve the calibration files and logs before recalibrating.

## A dataset will not train

Confirm the dataset ID is identical in the record and train commands. For
decode errors, consistency failures, dataset combining, or feature cleanup,
follow the
[Sourccey dataset tools guide](../04-ai/01-datasets.md).

Return to the [Sourccey guide](README.md).

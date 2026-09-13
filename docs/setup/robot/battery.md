# Battery

Sourccey uses the BQ34Z100 battery gauge over I2C. Stop `sourccey-host`
before running configuration or flash operations.

## Read battery status

```bash
uv run sourccey-battery
uv run sourccey-battery-check --pretty
```

These commands are read-only and are suitable for verifying wiring and gauge
communication.

## Inspect or configure the gauge

```bash
uv run sourccey-battery-configure info
uv run sourccey-battery-configure setup-4s-lifepo4
```

Configuration changes battery-gauge state. Confirm that the connected pack is
a four-cell LiFePO4 pack before applying that profile.

## Preview setup and recovery operations

Battery writes are not performed by the general setup command unless an
explicit option is supplied. Preview robot setup first:

```bash
python setup/setup.py robot --dry-run
```

Explicit provisioning and recovery commands are:

```bash
python setup/setup.py robot --configure-battery
python setup/setup.py robot --flash-battery df
python setup/setup.py robot --flash-battery bq
```

Golden-image flashing is also available through
`uv run sourccey-battery-flash`. Start with its `--dry-run` option before
writing to the gauge.

See the [battery implementation guide](../../../src/lerobot_robot_sourccey/battery/README.md)
for detailed diagnostics and recovery procedures.

Next, [calibrate Sourccey](calibrate.md), or return to the [setup
index](README.md).

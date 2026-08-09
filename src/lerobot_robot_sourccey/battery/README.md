# Sourccey Battery Setup (bq34z100)

This folder contains the battery setup and diagnostics tools for Sourccey.

If you only do one thing, follow **Quick Start** below in order.

## Files in this folder

- `configure_bq34z100.py` - write/read bq34z100 Data Flash fields over I2C
- `battery.py` - minimal frontend battery telemetry JSON
- `check_bq34z100.py` - deep diagnostics + watch mode for learning cycle checks
- `golden/flash_bq34z100.py` - TI FlashStream runner for `.df.fs` / `.bq.fs` files

## Prerequisites

- Run on the machine that has direct I2C access to the gauge (typically robot host/RPi).
- Gauge is reachable at I2C address `0x55` (default).
- Use `uv run ...` for all commands.

## I2C install and sanity checks (Linux/Raspberry Pi)

Install basic I2C tooling:

```bash
sudo apt update
sudo apt install -y i2c-tools
```

Enable I2C on Raspberry Pi (if not already enabled):

```bash
sudo raspi-config nonint do_i2c 0
sudo reboot
```

After reboot, verify I2C device nodes exist:

```bash
ls -l /dev/i2c-*
```

Check your user has I2C permission:

```bash
groups
```

If `i2c` is missing from your groups:

```bash
sudo usermod -aG i2c $USER
```

Then log out/log back in (or reboot) and verify again with `groups`.

Scan for devices (bus 1 is typical on Raspberry Pi):

```bash
sudo i2cdetect -y 1
```

Expected: the gauge appears at `0x55`.

Verify Python I2C dependency (`smbus2`) in this project env:

```bash
uv run python -c "import smbus2; print('smbus2 OK')"
```

## Quick Start

### 1) Confirm communication

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py info
```

Expected: JSON with `device_type`, `fw_version`, `chem_id`, `control_status`.

### 2) Apply standard Sourccey setup

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py setup-4s-lifepo4
```

This applies the project defaults (4S LiFePO4 profile, divider/config fields, thresholds, IT enable flow).

### 3) Verify key written fields

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py read-field --field voltage_divider
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py read-field --field flash_update_ok_cell_volt_mv
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py read-field --field number_of_series_cells
```

### 3b) Show all stats (pretty JSON, useful for debugging)

```bash
uv run python src/lerobot/scripts/sourccey/battery/check_bq34z100.py --pretty
```

```bash
uv run python src/lerobot/scripts/sourccey/battery/check_bq34z100.py --full --pretty
```

Use this output as your primary debugging snapshot when values look wrong.

### 4) Verify runtime telemetry

```bash
uv run python src/lerobot/scripts/sourccey/battery/battery.py
```

Expected: JSON with `voltage`, `current_a`, `remaining_capacity_ah`, `max_capacity_ah`, `state_of_charge`, `max_error`.

### 5) Run deeper health snapshot (recommended)

```bash
uv run python src/lerobot/scripts/sourccey/battery/check_bq34z100.py --pretty
```

Optional watch mode:

```bash
uv run python src/lerobot/scripts/sourccey/battery/check_bq34z100.py --watch --interval-s 5
```

### 6) Flash golden image (new or recovered chips)

Full firmware + data flash image:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py flash-golden --profile bq
```

Data-flash-only image:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py flash-golden --profile df
```

Preview without writes:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py flash-golden --profile bq --dry-run
```

## Common commands

List editable built-in fields:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py list-fields
```

Read one field:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py read-field --field <field_name>
```

Write one field:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py write-field --field <field_name> --value <int_value>
```

Set divider from resistor values and enable external divider mode:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py set-divider --top-ohm 249000 --bottom-ohm 16500 --enable-voltsel
```

Use non-default bus/address if needed:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py --bus 1 --address 0x55 info
```

Flash from a specific file path:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py flash-golden --fs-file src/lerobot/scripts/sourccey/battery/golden/0100_2_01-bq34z100.bq.fs
```

## Troubleshooting write failures

If you see errors like:

- `A read of data written failed comparison` (bqStudio), or
- `RuntimeError: Block verify failed for subclass=...`

then communication is working, but Data Flash commit was rejected by gauge state.

### Typical symptoms

- `configure_bq34z100.py info` works
- field writes are planned, but readback returns old values
- pack voltage in telemetry is clearly wrong (for example, ~2.2V for a 4S pack)

### What to check first

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py info
uv run python src/lerobot/scripts/sourccey/battery/battery.py
uv run python src/lerobot/scripts/sourccey/battery/check_bq34z100.py --pretty
```

If voltage path is wrong, writes can be blocked by flash update safety behavior.

### Recovery sequence (recommended)

1. Stop any other process talking to the gauge.
2. Reprogram matching default firmware image (`.srec`) for the detected FW family.
3. Re-run `setup-4s-lifepo4`.
4. Re-run the three verify reads in **Quick Start step 3**.
5. Confirm telemetry voltage is sane.

## Notes

- `configure_bq34z100.py` auto-unseals on write commands by default using standard keys.
- `--dry-run` shows planned writes without modifying flash.
- `--no-verify` skips readback verify (use only for debugging).

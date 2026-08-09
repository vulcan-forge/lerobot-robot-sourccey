# BQ34Z100 Golden Image Configuration

## Battery Information

- Battery: GoldenMate 12.8V 10Ah LiFePO4
- Configuration: 4S LiFePO4
- Gauge IC: BQ34Z100
- Learned Status: 6
- Grid Number: 14
- Cycle Count: 23

## Measured Values

- State of Charge (SOC): 1%
- Remaining Capacity: 6 mAh
- Full Charge Capacity (FCC): 12791 mAh
- True FCC: 12803 mAh
- State of Health (SOH): 100%
- Voltage: 11664 mV
- Current: 6 mA
- Average Current: 6 mA

## Charge Configuration

- Charge Voltage: 14300 mV
- Charge Current: 5000 mA

## Qmax / DOD Information

- Qstart: 12803 mAh
- DOD0: 16091
- Qmax DOD0: 16091
- Qmax Passed Q: -5 mAh
- DOD0 Passed Q: -3 mAh
- Qmax Time: 13 hr/16
- DOD0 Time: 8 hr/16

## Temperature

- Temperature: 15.1 °C
- Internal Temperature: 25.4 °C

## Bit Register Status

### Control Status

- FAS: Enabled
- SS: Enabled
- CAL_EN: Enabled
- CCA: Enabled
- BCA: Enabled
- CSV: Enabled

### Flags

- OTC: Enabled
- OTD: Enabled
- BATLOW: Enabled
- CHG_INH: Enabled
- XCHG: Enabled
- FC: Enabled
- DSG: Enabled
- REST: Enabled

### Flags B

- SOH: Enabled
- LIFE: Enabled
- FIRSTDOD: Enabled
- DTRC: Enabled

## Notes

- Learning cycle completed successfully.
- Gauge reached Learned Status 6.
- REST detection functioning correctly.
- Intended for export as:
    - `.bq.fs`
    - `.df.fs`
    - `.srec`

- Recommended for automated programming using Python + I2C.

## Flash Commands

Run the full firmware + data-flash image:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py flash-golden --profile bq
```

Run data-flash-only:

```bash
uv run python src/lerobot/scripts/sourccey/battery/configure_bq34z100.py flash-golden --profile df
```

Run the standalone flashstream runner directly:

```bash
uv run python src/lerobot/scripts/sourccey/battery/golden/flash_bq34z100.py --profile bq
```

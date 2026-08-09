#!/usr/bin/env python3
"""Read bq34z100 battery telemetry in a single script.

Outputs only frontend-facing fields:
- voltage
- current_a
- remaining_capacity_ah
- max_capacity_ah
- state_of_charge
- max_error
- chem_id
- error
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_I2C_ADDR = 0x55

# bq34z100 standard command addresses.
REG_STATE_OF_CHARGE = 0x02  # 1 byte (%)
REG_MAX_ERROR = 0x03  # 1 byte (%)
REG_REMAINING_CAPACITY = 0x04  # 2 bytes (mAh)
REG_FULL_CHARGE_CAPACITY = 0x06  # 2 bytes (mAh)
REG_VOLTAGE = 0x08  # 2 bytes (mV)
REG_AVERAGE_CURRENT = 0x0A  # 2 bytes (mA, signed)
REG_CONTROL = 0x00  # 2 bytes
CTRL_CHEM_ID = 0x0008


@dataclass
class BatteryData:
    voltage: float
    current_a: float
    remaining_capacity_ah: float
    max_capacity_ah: float
    state_of_charge: int
    max_error: int
    chem_id: int
    error: str | None


class BQ34Z100:
    def __init__(self, bus: int = 1, address: int = DEFAULT_I2C_ADDR) -> None:
        self._bus_num = bus
        self._addr = address

    @staticmethod
    def _open_bus(bus_num: int) -> Any:
        try:
            from smbus2 import SMBus
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("smbus2 is required. Install with: pip install smbus2") from exc
        return SMBus(bus_num)

    @staticmethod
    def _swap_u16(raw: int) -> int:
        return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)

    @staticmethod
    def _to_s16(raw: int) -> int:
        return raw - 0x10000 if raw & 0x8000 else raw

    def _read_u8(self, bus: Any, reg: int) -> int:
        return bus.read_byte_data(self._addr, reg)

    def _read_u16(self, bus: Any, reg: int, swap_word_bytes: bool) -> int:
        raw = bus.read_word_data(self._addr, reg)
        return self._swap_u16(raw) if swap_word_bytes else raw

    def _read_control_subcmd(self, bus: Any, subcmd: int, swap_word_bytes: bool) -> int:
        # Control() returns data at 0x00/0x01 after writing a 2-byte subcommand.
        bus.write_word_data(self._addr, REG_CONTROL, subcmd & 0xFFFF)
        raw = bus.read_word_data(self._addr, REG_CONTROL)
        return self._swap_u16(raw) if swap_word_bytes else raw

    def read(
        self,
        configured_rsense_mohm: float,
        actual_rsense_mohm: float,
        swap_word_bytes: bool,
    ) -> BatteryData:
        if actual_rsense_mohm <= 0.0 or configured_rsense_mohm <= 0.0:
            raise ValueError("Sense resistor values must be > 0")

        correction = configured_rsense_mohm / actual_rsense_mohm
        with self._open_bus(self._bus_num) as bus:
            soc_pct = self._read_u8(bus, REG_STATE_OF_CHARGE)
            max_error_pct = self._read_u8(bus, REG_MAX_ERROR)
            remaining_mah = self._read_u16(bus, REG_REMAINING_CAPACITY, swap_word_bytes)
            full_charge_mah = self._read_u16(bus, REG_FULL_CHARGE_CAPACITY, swap_word_bytes)
            voltage_mv = self._read_u16(bus, REG_VOLTAGE, swap_word_bytes)
            current_raw = self._read_u16(bus, REG_AVERAGE_CURRENT, swap_word_bytes)
            chem_id = self._read_control_subcmd(bus, CTRL_CHEM_ID, swap_word_bytes)

        current_ma = self._to_s16(current_raw)

        return BatteryData(
            voltage=voltage_mv / 1000.0,
            current_a=(current_ma * correction) / 1000.0,
            remaining_capacity_ah=(remaining_mah * correction) / 1000.0,
            max_capacity_ah=(full_charge_mah * correction) / 1000.0,
            state_of_charge=max(0, min(100, int(soc_pct))),
            max_error=max(0, min(100, int(max_error_pct))),
            chem_id=int(chem_id) & 0xFFFF,
            error=None,
        )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read bq34z100 battery telemetry")
    p.add_argument("--bus", type=int, default=1, help="I2C bus number (default: 1)")
    p.add_argument("--address", type=lambda x: int(x, 0), default=DEFAULT_I2C_ADDR, help="I2C address, e.g. 0x55")
    p.add_argument(
        "--actual-rsense-mohm",
        type=float,
        default=12.5,
        help="Actual SRP/SRN shunt resistor in milliohms",
    )
    p.add_argument(
        "--configured-rsense-mohm",
        type=float,
        default=12.5,
        help="Shunt value configured in gauge firmware (milliohms)",
    )
    p.add_argument(
        "--swap-word-bytes",
        action="store_true",
        help="Swap high/low bytes for 16-bit commands",
    )
    return p


def get_battery_data(
    bus: int = 1,
    address: int = DEFAULT_I2C_ADDR,
    configured_rsense_mohm: float = 12.5,
    actual_rsense_mohm: float = 12.5,
    swap_word_bytes: bool = False,
) -> BatteryData:
    gauge = BQ34Z100(bus=bus, address=address)
    return gauge.read(
        configured_rsense_mohm=configured_rsense_mohm,
        actual_rsense_mohm=actual_rsense_mohm,
        swap_word_bytes=swap_word_bytes,
    )


def main() -> int:
    args = _build_parser().parse_args()

    try:
        data = get_battery_data(
            bus=args.bus,
            address=args.address,
            configured_rsense_mohm=args.configured_rsense_mohm,
            actual_rsense_mohm=args.actual_rsense_mohm,
            swap_word_bytes=args.swap_word_bytes,
        )
    except Exception as exc:
        data = BatteryData(
            voltage=-1.0,
            current_a=-1.0,
            remaining_capacity_ah=-1.0,
            max_capacity_ah=-1.0,
            state_of_charge=-1,
            max_error=-1,
            chem_id=-1,
            error=str(exc),
        )

    payload = asdict(data)
    if payload["error"] is None:
        payload["voltage"] = round(float(payload["voltage"]), 3)
        payload["current_a"] = round(float(payload["current_a"]), 3)
        payload["remaining_capacity_ah"] = round(float(payload["remaining_capacity_ah"]), 3)
        payload["max_capacity_ah"] = round(float(payload["max_capacity_ah"]), 3)
        payload["chem_id_hex"] = f"0x{int(payload['chem_id']) & 0xFFFF:04X}"
    else:
        payload["chem_id_hex"] = None

    print(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Configure TI bq34z100 (-G1 / -R2) data flash over I2C (no bqStudio required).

This tool uses the data-flash block interface documented in the bq34z100 TRM:
- BlockDataControl() 0x61
- DataFlashClass() 0x3E
- DataFlashBlock() 0x3F
- BlockData() 0x40..0x5F
- BlockDataChecksum() 0x60

Typical uses:
- Enable external divider sensing (VOLTSEL bit)
- Set Voltage Divider from resistor values
- Set Design Capacity / Design Energy / Series Cells
- Set charge/discharge thresholds for a 4S LiFePO4 pack
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from typing import Any, Iterable


I2C_ADDR_DEFAULT = 0x55

REG_CONTROL = 0x00
REG_DF_CLASS = 0x3E
REG_DF_BLOCK = 0x3F
REG_BLOCKDATA_BASE = 0x40
REG_BLOCKDATA_CHECKSUM = 0x60
REG_BLOCKDATA_CONTROL = 0x61

CTRL_CONTROL_STATUS = 0x0000
CTRL_DEVICE_TYPE = 0x0001
CTRL_FW_VERSION = 0x0002
CTRL_CHEM_ID = 0x0008
CTRL_SEAL = 0x0020
CTRL_IT_ENABLE = 0x0021
DEFAULT_TARGET_CHEM_ID = 0x4203

# TRM default unseal key bytes shown as 0x36720414 (two 16-bit writes)
DEFAULT_UNSEAL_KEY1 = 0x0414
DEFAULT_UNSEAL_KEY2 = 0x3672


@dataclass(frozen=True)
class FieldSpec:
    name: str
    subclass: int
    offset: int
    dtype: str
    description: str

    @property
    def size(self) -> int:
        t = self.dtype.lower()
        if t.endswith("1"):
            return 1
        if t.endswith("2"):
            return 2
        if t.endswith("4"):
            return 4
        raise ValueError(f"Unsupported dtype: {self.dtype}")

    @property
    def signed(self) -> bool:
        return self.dtype.lower().startswith("i")

    @property
    def is_hex(self) -> bool:
        return self.dtype.lower().startswith("h")


# bq34z100-R2 fields (TRM Table 7-1)
FIELDS: dict[str, FieldSpec] = {
    "pack_configuration": FieldSpec(
        "pack_configuration", 64, 0, "H2", "Pack Configuration flags (bit3 in MSB = VOLTSEL)"
    ),
    "pack_configuration_b": FieldSpec("pack_configuration_b", 64, 2, "H1", "Pack Configuration B flags"),
    "pack_configuration_c": FieldSpec("pack_configuration_c", 64, 3, "H1", "Pack Configuration C flags"),
    "number_of_series_cells": FieldSpec("number_of_series_cells", 64, 7, "U1", "Number of series cells"),
    "flash_update_ok_cell_volt_mv": FieldSpec(
        "flash_update_ok_cell_volt_mv", 68, 0, "I2", "Flash Update OK Cell Voltage (mV)"
    ),
    "design_capacity_mah": FieldSpec("design_capacity_mah", 48, 11, "I2", "Design Capacity (mAh)"),
    "design_energy_cwh": FieldSpec("design_energy_cwh", 48, 13, "I2", "Design Energy (cWh)"),
    "cell_charge_voltage_t1_t2_mv": FieldSpec(
        "cell_charge_voltage_t1_t2_mv", 48, 17, "U2", "Cell Charge Voltage T1-T2 (mV)"
    ),
    "cell_charge_voltage_t2_t3_mv": FieldSpec(
        "cell_charge_voltage_t2_t3_mv", 48, 19, "U2", "Cell Charge Voltage T2-T3 (mV)"
    ),
    "cell_charge_voltage_t3_t4_mv": FieldSpec(
        "cell_charge_voltage_t3_t4_mv", 48, 21, "U2", "Cell Charge Voltage T3-T4 (mV)"
    ),
    "taper_current_ma": FieldSpec("taper_current_ma", 36, 0, "I2", "Taper Current (mA)"),
    "quit_current_ma": FieldSpec("quit_current_ma", 81, 4, "I2", "Quit Current (mA)"),
    "cell_terminate_voltage_mv": FieldSpec(
        "cell_terminate_voltage_mv", 80, 53, "I2", "Cell Terminate Voltage (mV)"
    ),
    "qmax_cell0_mah": FieldSpec("qmax_cell0_mah", 82, 0, "I2", "Qmax Cell0 (mAh)"),
    "update_status": FieldSpec("update_status", 82, 4, "H1", "Gas Gauging State Update Status"),
    "voltage_divider": FieldSpec("voltage_divider", 104, 14, "U2", "Voltage Divider (mV ratio)"),
}


class BQ34Z100R2:
    def __init__(self, bus_num: int, address: int) -> None:
        self.bus_num = bus_num
        self.address = address

    @staticmethod
    def _open_bus(bus_num: int) -> Any:
        try:
            from smbus2 import SMBus
        except ImportError as exc:
            raise SystemExit("smbus2 is required. Install with: pip install smbus2") from exc
        return SMBus(bus_num)

    def _read_word(self, bus: Any, reg: int) -> int:
        return bus.read_word_data(self.address, reg)

    def _write_word(self, bus: Any, reg: int, value: int) -> None:
        bus.write_word_data(self.address, reg, value & 0xFFFF)

    def _read_byte(self, bus: Any, reg: int) -> int:
        return bus.read_byte_data(self.address, reg)

    def _write_byte(self, bus: Any, reg: int, value: int) -> None:
        bus.write_byte_data(self.address, reg, value & 0xFF)

    def read_control_subcmd(self, subcmd: int, delay_s: float = 0.02) -> int:
        with self._open_bus(self.bus_num) as bus:
            self._write_word(bus, REG_CONTROL, subcmd)
            time.sleep(delay_s)
            return self._read_word(bus, REG_CONTROL)

    def send_control_subcmd(self, subcmd: int) -> None:
        with self._open_bus(self.bus_num) as bus:
            self._write_word(bus, REG_CONTROL, subcmd)

    def unseal(self, key1: int, key2: int, delay_s: float = 0.02) -> None:
        with self._open_bus(self.bus_num) as bus:
            self._write_word(bus, REG_CONTROL, key1)
            time.sleep(delay_s)
            self._write_word(bus, REG_CONTROL, key2)
            time.sleep(delay_s)

    @staticmethod
    def _calc_block_checksum(block: list[int]) -> int:
        if len(block) != 32:
            raise ValueError("Data-flash block must be exactly 32 bytes")
        return (0xFF - (sum(block) & 0xFF)) & 0xFF

    def _select_df_block(self, bus: Any, subclass: int, block: int) -> None:
        self._write_byte(bus, REG_BLOCKDATA_CONTROL, 0x00)
        self._write_byte(bus, REG_DF_CLASS, subclass)
        self._write_byte(bus, REG_DF_BLOCK, block)
        time.sleep(0.02)

    def read_df_block(self, subclass: int, block: int) -> list[int]:
        with self._open_bus(self.bus_num) as bus:
            self._select_df_block(bus, subclass, block)
            return [self._read_byte(bus, REG_BLOCKDATA_BASE + i) for i in range(32)]

    def write_df_block(
        self,
        subclass: int,
        block: int,
        new_block: Iterable[int],
        verify: bool = True,
        verify_indices: set[int] | None = None,
    ) -> None:
        new_vals = [int(v) & 0xFF for v in new_block]
        if len(new_vals) != 32:
            raise ValueError("new_block must contain exactly 32 bytes")

        with self._open_bus(self.bus_num) as bus:
            self._select_df_block(bus, subclass, block)
            indices_to_write = range(32) if verify_indices is None else sorted(verify_indices)
            for i in indices_to_write:
                value = new_vals[i]
                self._write_byte(bus, REG_BLOCKDATA_BASE + i, value)

            checksum = self._calc_block_checksum(new_vals)
            self._write_byte(bus, REG_BLOCKDATA_CHECKSUM, checksum)
            time.sleep(0.06)

            if verify:
                indices_to_check = range(32) if verify_indices is None else sorted(verify_indices)
                last_read_back: list[int] | None = None
                last_mismatches: list[int] = []
                for _ in range(3):
                    self._select_df_block(bus, subclass, block)
                    read_back = [self._read_byte(bus, REG_BLOCKDATA_BASE + i) for i in range(32)]
                    mismatches = [i for i in indices_to_check if read_back[i] != new_vals[i]]
                    if not mismatches:
                        return
                    last_read_back = read_back
                    last_mismatches = mismatches
                    time.sleep(0.08)
                raise RuntimeError(
                    f"Block verify failed for subclass={subclass} block={block} "
                    f"at indices={last_mismatches}: wrote={new_vals!r}, read={last_read_back!r}"
                )

    def read_df_bytes(self, subclass: int, offset: int, size: int) -> bytes:
        out = bytearray()
        remaining = size
        cursor = offset
        while remaining > 0:
            block = cursor // 32
            index = cursor % 32
            chunk = min(remaining, 32 - index)
            block_data = self.read_df_block(subclass, block)
            out.extend(block_data[index : index + chunk])
            cursor += chunk
            remaining -= chunk
        return bytes(out)

    def write_df_bytes(self, subclass: int, offset: int, data: bytes, verify: bool = True) -> None:
        remaining = len(data)
        cursor = offset
        src_idx = 0
        while remaining > 0:
            block = cursor // 32
            index = cursor % 32
            chunk = min(remaining, 32 - index)

            block_data = self.read_df_block(subclass, block)
            changed_indices: set[int] = set()
            for i in range(chunk):
                block_index = index + i
                new_val = data[src_idx + i]
                if block_data[block_index] != new_val:
                    block_data[block_index] = new_val
                    changed_indices.add(block_index)

            if changed_indices:
                self.write_df_block(
                    subclass,
                    block,
                    block_data,
                    verify=verify,
                    verify_indices=changed_indices,
                )

            cursor += chunk
            src_idx += chunk
            remaining -= chunk

    def read_field(self, spec: FieldSpec) -> int:
        raw = self.read_df_bytes(spec.subclass, spec.offset, spec.size)
        return int.from_bytes(raw, byteorder="big", signed=spec.signed)

    def write_field(self, spec: FieldSpec, value: int, verify: bool = True) -> None:
        raw = int(value).to_bytes(spec.size, byteorder="big", signed=spec.signed)
        self.write_df_bytes(spec.subclass, spec.offset, raw, verify=verify)


@dataclass
class PendingWrite:
    spec: FieldSpec
    old_value: int
    new_value: int


def calculate_voltage_divider_value(top_ohm: float, bottom_ohm: float) -> int:
    if top_ohm < 0 or bottom_ohm <= 0:
        raise ValueError("Resistor values must satisfy top >= 0 and bottom > 0")
    ratio = (top_ohm + bottom_ohm) / bottom_ohm
    return int(round(ratio * 1000.0))


def set_pack_config_voltsel(pack_config: int, enabled: bool) -> int:
    msb = (pack_config >> 8) & 0xFF
    lsb = pack_config & 0xFF
    if enabled:
        msb |= (1 << 3)
    else:
        msb &= ~(1 << 3)
    return ((msb & 0xFF) << 8) | lsb


def format_value(spec: FieldSpec, value: int) -> str:
    if spec.is_hex:
        width = spec.size * 2
        return f"0x{value & ((1 << (spec.size * 8)) - 1):0{width}X}"
    return str(value)


def maybe_unseal(gauge: BQ34Z100R2, args: argparse.Namespace, writing: bool) -> None:
    if not writing or args.dry_run:
        return
    key1: int | None = None
    key2: int | None = None

    if args.default_unseal:
        key1 = DEFAULT_UNSEAL_KEY1
        key2 = DEFAULT_UNSEAL_KEY2
    elif args.unseal_key1 is not None or args.unseal_key2 is not None:
        if args.unseal_key1 is None or args.unseal_key2 is None:
            raise SystemExit("Provide both --unseal-key1 and --unseal-key2")
        key1 = args.unseal_key1
        key2 = args.unseal_key2

    if key1 is not None and key2 is not None:
        gauge.unseal(key1, key2)


def cmd_info(gauge: BQ34Z100R2, _: argparse.Namespace) -> int:
    info = {
        "device_type": gauge.read_control_subcmd(CTRL_DEVICE_TYPE),
        "fw_version": gauge.read_control_subcmd(CTRL_FW_VERSION),
        "chem_id": gauge.read_control_subcmd(CTRL_CHEM_ID),
        "control_status": gauge.read_control_subcmd(CTRL_CONTROL_STATUS),
    }
    print(json.dumps({k: f"0x{v:04X}" for k, v in info.items()}, indent=2))
    return 0


def cmd_list_fields(_: BQ34Z100R2, __: argparse.Namespace) -> int:
    for key in sorted(FIELDS):
        s = FIELDS[key]
        print(f"{key:30s} subclass={s.subclass:3d} offset={s.offset:3d} type={s.dtype:>2s}  {s.description}")
    return 0


def cmd_read_field(gauge: BQ34Z100R2, args: argparse.Namespace) -> int:
    spec = FIELDS[args.field]
    value = gauge.read_field(spec)
    print(
        json.dumps(
            {
                "field": spec.name,
                "subclass": spec.subclass,
                "offset": spec.offset,
                "type": spec.dtype,
                "value": format_value(spec, value),
            },
            indent=2,
        )
    )
    return 0


def apply_writes(gauge: BQ34Z100R2, writes: list[PendingWrite], verify: bool, dry_run: bool) -> None:
    writes_to_apply = [w for w in writes if w.old_value != w.new_value]
    if not writes_to_apply:
        print("No changes requested.")
        return

    print("Planned writes:")
    for w in writes_to_apply:
        print(
            f"- {w.spec.name}: {format_value(w.spec, w.old_value)} -> {format_value(w.spec, w.new_value)} "
            f"(subclass={w.spec.subclass}, offset={w.spec.offset}, type={w.spec.dtype})"
        )

    if dry_run:
        print("Dry-run enabled: no writes performed.")
        return

    for w in writes_to_apply:
        gauge.write_field(w.spec, w.new_value, verify=verify)


def cmd_write_field(gauge: BQ34Z100R2, args: argparse.Namespace) -> int:
    spec = FIELDS[args.field]
    maybe_unseal(gauge, args, writing=True)
    old_value = gauge.read_field(spec)
    writes = [PendingWrite(spec=spec, old_value=old_value, new_value=args.value)]
    apply_writes(gauge, writes, verify=not args.no_verify, dry_run=args.dry_run)

    if args.seal_after and not args.dry_run:
        gauge.send_control_subcmd(CTRL_SEAL)
    return 0


def cmd_set_divider(gauge: BQ34Z100R2, args: argparse.Namespace) -> int:
    maybe_unseal(gauge, args, writing=True)

    divider = calculate_voltage_divider_value(args.top_ohm, args.bottom_ohm)
    writes: list[PendingWrite] = []

    div_spec = FIELDS["voltage_divider"]
    old_div = gauge.read_field(div_spec)
    writes.append(PendingWrite(spec=div_spec, old_value=old_div, new_value=divider))

    if args.enable_voltsel or args.disable_voltsel:
        pack_spec = FIELDS["pack_configuration"]
        old_pack = gauge.read_field(pack_spec)
        new_pack = set_pack_config_voltsel(old_pack, enabled=args.enable_voltsel and not args.disable_voltsel)
        writes.append(PendingWrite(spec=pack_spec, old_value=old_pack, new_value=new_pack))

    print(f"Computed voltage_divider={divider} from Rtop={args.top_ohm}ohm, Rbottom={args.bottom_ohm}ohm")
    apply_writes(gauge, writes, verify=not args.no_verify, dry_run=args.dry_run)

    if args.seal_after and not args.dry_run:
        gauge.send_control_subcmd(CTRL_SEAL)
    return 0


def wait_for_update_status(
    gauge: BQ34Z100R2,
    expected_value: int,
    timeout_s: float,
    poll_interval_s: float = 0.2,
) -> int:
    spec = FIELDS["update_status"]
    timeout = max(0.0, float(timeout_s))
    deadline = time.monotonic() + timeout
    last_value = gauge.read_field(spec)
    while last_value != expected_value and time.monotonic() < deadline:
        time.sleep(poll_interval_s)
        last_value = gauge.read_field(spec)
    return last_value


def control_status_qen_enabled(control_status: int) -> bool:
    return bool(int(control_status) & 0x0001)


def update_status_indicates_learning_started(update_status: int) -> bool:
    # Accept exact 0x04 as the fresh IT_ENABLE transition, and also tolerate
    # later progress values where that bit remains set (for example 0x06).
    return bool(int(update_status) & 0x04)


def cmd_setup_4s_lifepo4(gauge: BQ34Z100R2, args: argparse.Namespace) -> int:
    maybe_unseal(gauge, args, writing=True)

    observed_chem_id = gauge.read_control_subcmd(CTRL_CHEM_ID)
    if args.require_chem_id and observed_chem_id != args.chem_id:
        raise RuntimeError(
            "CHEM_ID mismatch: "
            f"observed=0x{observed_chem_id:04X} ({observed_chem_id}), "
            f"expected=0x{args.chem_id:04X} ({args.chem_id}). "
            "On bq34z100-R2, Control() subcommand CHEM_ID (0x0008) is a read/report command; "
            "program the desired chemistry profile (golden image) with TI tooling, then rerun setup."
        )
    print(f"CHEM_ID check: 0x{observed_chem_id:04X} ({observed_chem_id})")
    if not args.require_chem_id and observed_chem_id != args.chem_id:
        print(
            "WARNING: CHEM_ID does not match profile expectation "
            f"(observed=0x{observed_chem_id:04X}, expected=0x{args.chem_id:04X}). "
            "Continuing because --require-chem-id is disabled."
        )

    writes: list[PendingWrite] = []

    # Series cells
    spec_series = FIELDS["number_of_series_cells"]
    old_series = gauge.read_field(spec_series)
    writes.append(PendingWrite(spec=spec_series, old_value=old_series, new_value=args.series_cells))

    # Design capacity and optional Qmax seed
    spec_cap = FIELDS["design_capacity_mah"]
    old_cap = gauge.read_field(spec_cap)
    writes.append(PendingWrite(spec=spec_cap, old_value=old_cap, new_value=args.design_capacity_mah))

    if args.set_qmax_from_capacity:
        spec_qmax = FIELDS["qmax_cell0_mah"]
        old_qmax = gauge.read_field(spec_qmax)
        writes.append(PendingWrite(spec=spec_qmax, old_value=old_qmax, new_value=args.design_capacity_mah))

    # Design energy (cWh) from design V and capacity
    if args.design_voltage_mv is not None:
        design_energy_cwh = int(round(args.design_capacity_mah * args.design_voltage_mv / 10000.0))
        spec_energy = FIELDS["design_energy_cwh"]
        old_energy = gauge.read_field(spec_energy)
        writes.append(PendingWrite(spec=spec_energy, old_value=old_energy, new_value=design_energy_cwh))

    # Current thresholds and terminate voltage
    if args.taper_current_ma is not None:
        spec_taper = FIELDS["taper_current_ma"]
        old_taper = gauge.read_field(spec_taper)
        writes.append(PendingWrite(spec=spec_taper, old_value=old_taper, new_value=args.taper_current_ma))

    if args.quit_current_ma is not None:
        spec_quit = FIELDS["quit_current_ma"]
        old_quit = gauge.read_field(spec_quit)
        writes.append(PendingWrite(spec=spec_quit, old_value=old_quit, new_value=args.quit_current_ma))

    if args.cell_terminate_voltage_mv is not None:
        spec_term = FIELDS["cell_terminate_voltage_mv"]
        old_term = gauge.read_field(spec_term)
        writes.append(PendingWrite(spec=spec_term, old_value=old_term, new_value=args.cell_terminate_voltage_mv))

    # Divider + VOLTSEL
    if args.voltage_divider is not None:
        if args.voltage_divider <= 0:
            raise SystemExit("--voltage-divider must be > 0")
        divider = args.voltage_divider
    else:
        divider = calculate_voltage_divider_value(args.top_ohm, args.bottom_ohm)
    spec_div = FIELDS["voltage_divider"]
    old_div = gauge.read_field(spec_div)
    writes.append(PendingWrite(spec=spec_div, old_value=old_div, new_value=divider))

    if args.set_voltsel:
        spec_pack = FIELDS["pack_configuration"]
        old_pack = gauge.read_field(spec_pack)
        new_pack = set_pack_config_voltsel(old_pack, enabled=True)
        writes.append(PendingWrite(spec=spec_pack, old_value=old_pack, new_value=new_pack))

    # Optional: set all temperature-range charge voltages from pack-level target.
    if args.pack_charge_voltage_mv is not None:
        cell_cv = int(round(args.pack_charge_voltage_mv / args.series_cells))
        for field_name in (
            "cell_charge_voltage_t1_t2_mv",
            "cell_charge_voltage_t2_t3_mv",
            "cell_charge_voltage_t3_t4_mv",
        ):
            spec = FIELDS[field_name]
            old = gauge.read_field(spec)
            writes.append(PendingWrite(spec=spec, old_value=old, new_value=cell_cv))

    print(
        f"Profile: {args.series_cells}S LiFePO4, design_capacity={args.design_capacity_mah}mAh, "
        f"charge_voltage={args.pack_charge_voltage_mv}mV, "
        f"taper_current={args.taper_current_ma}mA, quit_current={args.quit_current_ma}mA, "
        f"divider={divider}, voltsel={'on' if args.set_voltsel else 'unchanged'}"
    )
    apply_writes(gauge, writes, verify=not args.no_verify, dry_run=args.dry_run)

    # Optional: reset UpdateStatus for fresh learning run.
    # This field is gauge-state managed and may reject host writes in some modes.
    if args.reset_update_status:
        spec_us = FIELDS["update_status"]
        old_us = gauge.read_field(spec_us)
        update_status_write = [PendingWrite(spec=spec_us, old_value=old_us, new_value=0x00)]
        try:
            apply_writes(gauge, update_status_write, verify=not args.no_verify, dry_run=args.dry_run)
        except RuntimeError as exc:
            print(
                "WARNING: Could not reset UpdateStatus to 0x00. "
                "Continuing setup because this register may be managed by gauge state. "
                f"Details: {exc}"
            )

    if args.enable_it and not args.dry_run:
        initial_control_status = gauge.read_control_subcmd(CTRL_CONTROL_STATUS)
        initial_update_status = gauge.read_field(FIELDS["update_status"])

        if control_status_qen_enabled(initial_control_status):
            print(
                "Skipping IT_ENABLE because QEN is already set "
                f"(ControlStatus=0x{initial_control_status:04X}, UpdateStatus=0x{initial_update_status:02X})."
            )
        else:
            print("Sending IT_ENABLE (0x0021) to start learning.")
            gauge.send_control_subcmd(CTRL_IT_ENABLE)
            if args.verify_update_status:
                observed_update_status = wait_for_update_status(
                    gauge=gauge,
                    expected_value=0x04,
                    timeout_s=args.update_status_timeout_s,
                )
                if not update_status_indicates_learning_started(observed_update_status):
                    raise RuntimeError(
                        "Expected UpdateStatus to indicate learning start after IT_ENABLE but observed "
                        f"0x{observed_update_status:02X}. Check gauge state and learning preconditions."
                    )
                if observed_update_status == 0x04:
                    print("Learning start confirmed: UpdateStatus=0x04.")
                else:
                    print(f"Learning state accepted: UpdateStatus=0x{observed_update_status:02X}.")
    elif args.verify_update_status and not args.dry_run:
        print("Skipping UpdateStatus verification because --enable-it is disabled.")

    if args.seal_after and not args.dry_run:
        gauge.send_control_subcmd(CTRL_SEAL)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Configure bq34z100 (-G1 / -R2) data flash over I2C")
    p.add_argument("--bus", type=int, default=1, help="I2C bus (default: 1)")
    p.add_argument("--address", type=lambda x: int(x, 0), default=I2C_ADDR_DEFAULT, help="I2C address (default: 0x55)")

    # Write-access helpers
    p.add_argument(
        "--default-unseal",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use TRM default unseal keys (0x0414, 0x3672). Default: enabled",
    )
    p.add_argument("--unseal-key1", type=lambda x: int(x, 0), default=None, help="Custom unseal key word 1")
    p.add_argument("--unseal-key2", type=lambda x: int(x, 0), default=None, help="Custom unseal key word 2")
    p.add_argument("--seal-after", action="store_true", help="Send SEAL command after writes")
    p.add_argument("--dry-run", action="store_true", help="Print planned writes but do not write")
    p.add_argument("--no-verify", action="store_true", help="Skip readback verify after block write")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="Read basic control info (device type, fw, chem, status)")
    sub.add_parser("list-fields", help="List built-in editable fields")

    p_read = sub.add_parser("read-field", help="Read one built-in data flash field")
    p_read.add_argument("--field", choices=sorted(FIELDS), required=True)

    p_write = sub.add_parser("write-field", help="Write one built-in data flash field")
    p_write.add_argument("--field", choices=sorted(FIELDS), required=True)
    p_write.add_argument("--value", type=lambda x: int(x, 0), required=True)

    p_div = sub.add_parser("set-divider", help="Set Voltage Divider and optionally VOLTSEL")
    p_div.add_argument("--top-ohm", type=float, required=True, help="Top resistor (pack+ to BAT), ohms")
    p_div.add_argument("--bottom-ohm", type=float, required=True, help="Bottom resistor (BAT to GND), ohms")
    p_div_mode = p_div.add_mutually_exclusive_group()
    p_div_mode.add_argument("--enable-voltsel", action="store_true", help="Set PackConfig[VOLTSEL]=1")
    p_div_mode.add_argument("--disable-voltsel", action="store_true", help="Set PackConfig[VOLTSEL]=0")

    p_setup = sub.add_parser("setup-4s-lifepo4", help="Apply a practical 4S LiFePO4 starter configuration")
    p_setup.add_argument(
        "--chem-id",
        type=lambda x: int(x, 0),
        default=DEFAULT_TARGET_CHEM_ID,
        help="Expected CHEM_ID before applying setup (default: 0x4203)",
    )
    p_setup.add_argument(
        "--require-chem-id",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require CHEM_ID to match --chem-id before setup writes (default: disabled)",
    )
    p_setup.add_argument(
        "--design-capacity-mah",
        type=int,
        default=10000,
        help="Pack design capacity in mAh (default: 10000)",
    )
    p_setup.add_argument("--series-cells", type=int, default=4, help="Series cells (default: 4)")
    p_setup.add_argument("--design-voltage-mv", type=int, default=12800, help="Nominal pack voltage for design energy")
    p_setup.add_argument(
        "--voltage-divider",
        type=int,
        default=4023,
        help="Direct Voltage Divider data-flash value (default: 4023)",
    )
    p_setup.add_argument("--top-ohm", type=float, default=249000.0, help="Top divider resistor in ohms")
    p_setup.add_argument("--bottom-ohm", type=float, default=16500.0, help="Bottom divider resistor in ohms")
    p_setup.add_argument(
        "--set-voltsel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable external-divider mode (default: enabled)",
    )
    p_setup.add_argument(
        "--taper-current-ma",
        type=int,
        default=250,
        help=(
            "Taper current in mA (default: 250). "
            "Tune to your charger's end-of-charge tail current."
        ),
    )
    p_setup.add_argument(
        "--quit-current-ma",
        type=int,
        default=10,
        help=(
            "Quit current in mA (default: 10). "
            "FC requires current to stay above this threshold while below taper."
        ),
    )
    p_setup.add_argument(
        "--cell-terminate-voltage-mv",
        type=int,
        default=2850,
        help="Per-cell terminate voltage in mV (default: 2850)",
    )
    p_setup.add_argument(
        "--pack-charge-voltage-mv",
        type=int,
        default=14300,
        help=(
            "Pack charge voltage in mV; sets all three cell charge-voltage fields equally "
            "(default: 14300 for Sourccey 4S charger behavior)."
        ),
    )
    p_setup.add_argument(
        "--set-qmax-from-capacity",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also set Qmax Cell0 equal to design capacity (default: enabled)",
    )
    p_setup.add_argument(
        "--reset-update-status",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Set UpdateStatus=0x00 for a fresh learning cycle (default: disabled)",
    )
    p_setup.add_argument(
        "--enable-it",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Send IT_ENABLE (0x0021) after setup writes (default: enabled)",
    )
    p_setup.add_argument(
        "--verify-update-status",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="After IT_ENABLE, require UpdateStatus to become 0x04 (default: enabled)",
    )
    p_setup.add_argument(
        "--update-status-timeout-s",
        type=float,
        default=4.0,
        help="Seconds to wait for UpdateStatus=0x04 after IT_ENABLE (default: 4.0)",
    )

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    gauge = BQ34Z100R2(bus_num=args.bus, address=args.address)

    try:
        if args.cmd == "info":
            return cmd_info(gauge, args)
        if args.cmd == "list-fields":
            return cmd_list_fields(gauge, args)
        if args.cmd == "read-field":
            return cmd_read_field(gauge, args)
        if args.cmd == "write-field":
            return cmd_write_field(gauge, args)
        if args.cmd == "set-divider":
            return cmd_set_divider(gauge, args)
        if args.cmd == "setup-4s-lifepo4":
            return cmd_setup_4s_lifepo4(gauge, args)
    except OSError as exc:
        raise SystemExit(f"I2C error (errno={getattr(exc, 'errno', None)}): {exc}") from exc

    raise SystemExit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())

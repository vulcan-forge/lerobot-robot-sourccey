#!/usr/bin/env python3
"""Dump bq34z100 diagnostics as JSON.

This script is read-only.

Default output is compact and operator-focused:
- voltage/current/SOC/capacity
- pack config + detected series-cell count
- key gauge health/config values
- FC-learning thresholds + live gate snapshot
- decoded status bits (FC/VOK/RUP_DIS/QEN)

Use ``--full`` for a detailed dump with raw registers/fields/blocks.
Use ``--watch`` for 5-10s learning-cycle monitoring with optional CSV/JSONL logs.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lerobot_robot_sourccey.battery.battery import (
    DEFAULT_I2C_ADDR,
    REG_AVERAGE_CURRENT,
    REG_FULL_CHARGE_CAPACITY,
    REG_MAX_ERROR,
    REG_REMAINING_CAPACITY,
    REG_STATE_OF_CHARGE,
    REG_VOLTAGE,
    get_battery_data,
)
from lerobot_robot_sourccey.battery.configure_bq34z100 import (
    CTRL_CHEM_ID,
    CTRL_CONTROL_STATUS,
    CTRL_DEVICE_TYPE,
    CTRL_FW_VERSION,
    FIELDS,
    BQ34Z100R2,
)

REG_FLAGS = 0x0E


def _word_views(value: int) -> dict[str, Any]:
    v = int(value) & 0xFFFF
    return {
        "int": v,
        "hex": f"0x{v:04X}",
        "bin": f"0b{v:016b}",
    }


def _swap_u16(raw: int) -> int:
    return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)


def _to_s16(raw: int) -> int:
    return raw - 0x10000 if raw & 0x8000 else raw


def _calc_df_block_checksum(block: list[int]) -> int:
    return (0xFF - (sum(block) & 0xFF)) & 0xFF


def _read_raw_standard_registers(
    gauge: BQ34Z100R2,
    *,
    swap_word_bytes: bool,
) -> dict[str, Any]:
    try:
        from smbus2 import SMBus
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("smbus2 is required. Install with: pip install smbus2") from exc

    out: dict[str, Any] = {}
    with SMBus(gauge.bus_num) as bus:
        out["state_of_charge"] = {
            "reg": "0x02",
            "raw_u8": int(bus.read_byte_data(gauge.address, REG_STATE_OF_CHARGE)),
        }
        out["max_error"] = {
            "reg": "0x03",
            "raw_u8": int(bus.read_byte_data(gauge.address, REG_MAX_ERROR)),
        }

        word_regs = {
            "remaining_capacity_mah_raw": REG_REMAINING_CAPACITY,
            "full_charge_capacity_mah_raw": REG_FULL_CHARGE_CAPACITY,
            "voltage_mv_raw": REG_VOLTAGE,
            "average_current_ma_raw": REG_AVERAGE_CURRENT,
            "flags_raw": REG_FLAGS,
        }
        for name, reg in word_regs.items():
            raw = int(bus.read_word_data(gauge.address, reg))
            normalized = _swap_u16(raw) if swap_word_bytes else raw
            out[name] = {
                "reg": f"0x{reg:02X}",
                "raw_word": _word_views(raw),
                "normalized_word": _word_views(normalized),
            }

        cur_norm = out["average_current_ma_raw"]["normalized_word"]["int"]
        out["average_current_ma_raw"]["normalized_signed"] = _to_s16(cur_norm)

    return out


def _read_control_info(gauge: BQ34Z100R2) -> dict[str, Any]:
    device_type = gauge.read_control_subcmd(CTRL_DEVICE_TYPE)
    fw_version = gauge.read_control_subcmd(CTRL_FW_VERSION)
    chem_id = gauge.read_control_subcmd(CTRL_CHEM_ID)
    control_status = gauge.read_control_subcmd(CTRL_CONTROL_STATUS)
    return {
        "device_type": _word_views(device_type),
        "fw_version": _word_views(fw_version),
        "chem_id": _word_views(chem_id),
        "control_status": _word_views(control_status),
    }


def _decode_control_status_flags(control_status: int) -> dict[str, bool]:
    # CONTROL_STATUS low-byte bits from TI docs:
    # bit0=QEN, bit1=VOK, bit2=RUP_DIS
    value = int(control_status) & 0xFFFF
    return {
        "QEN": bool(value & (1 << 0)),
        "VOK": bool(value & (1 << 1)),
        "RUP_DIS": bool(value & (1 << 2)),
    }


def _decode_operation_flags(flags_word: int) -> dict[str, bool]:
    # Flags() bit9: FC (Full Charge detected)
    value = int(flags_word) & 0xFFFF
    return {
        "FC": bool(value & (1 << 9)),
    }


def _read_data_flash_fields(gauge: BQ34Z100R2) -> dict[str, Any]:
    fields_out: dict[str, Any] = {}
    for key in sorted(FIELDS):
        spec = FIELDS[key]
        value = gauge.read_field(spec)
        raw_bytes = gauge.read_df_bytes(spec.subclass, spec.offset, spec.size)
        entry: dict[str, Any] = {
            "name": spec.name,
            "description": spec.description,
            "subclass": spec.subclass,
            "offset": spec.offset,
            "size": spec.size,
            "type": spec.dtype,
            "value_int": int(value),
            "value_hex": f"0x{(int(value) & ((1 << (spec.size * 8)) - 1)):0{spec.size * 2}X}",
            "value_bin": f"0b{(int(value) & ((1 << (spec.size * 8)) - 1)):0{spec.size * 8}b}",
            "raw_bytes_hex": raw_bytes.hex().upper(),
        }
        fields_out[key] = entry
    return fields_out


def _read_data_flash_blocks(gauge: BQ34Z100R2) -> list[dict[str, Any]]:
    used_blocks = sorted({(spec.subclass, spec.offset // 32) for spec in FIELDS.values()})
    blocks: list[dict[str, Any]] = []
    for subclass, block_idx in used_blocks:
        data = gauge.read_df_block(subclass, block_idx)
        checksum = _calc_df_block_checksum(data)
        blocks.append(
            {
                "subclass": subclass,
                "block_index": block_idx,
                "raw_bytes_hex": [f"{b:02X}" for b in data],
                "calculated_checksum": f"0x{checksum:02X}",
            }
        )
    return blocks


def _read_learning_thresholds(gauge: BQ34Z100R2) -> dict[str, int]:
    # Gas Gauging Current Thresholds live in subclass 81:
    # 0: Dsg Current Threshold, 2: Chg Current Threshold, 4: Quit Current.
    def _read_i16(subclass: int, offset: int) -> int:
        raw = gauge.read_df_bytes(subclass, offset, 2)
        return int.from_bytes(raw, byteorder="big", signed=True)

    return {
        "dsg_current_threshold_ma": _read_i16(81, 0),
        "chg_current_threshold_ma": _read_i16(81, 2),
        "quit_current_ma": _read_i16(81, 4),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dump detailed bq34z100 diagnostics as JSON")
    p.add_argument("--bus", type=int, default=1, help="I2C bus number (default: 1)")
    p.add_argument("--address", type=lambda x: int(x, 0), default=DEFAULT_I2C_ADDR, help="I2C address (default: 0x55)")
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
        help="Swap high/low bytes for 16-bit standard command reads",
    )
    p.add_argument(
        "--include-block-dump",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include raw 32-byte data-flash blocks containing known fields (default: enabled)",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Output full diagnostic payload (default: compact summary)",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON (default is compact JSON)",
    )
    p.add_argument(
        "--watch",
        action="store_true",
        help="Continuously sample until interrupted (Ctrl+C)",
    )
    p.add_argument(
        "--interval-s",
        type=float,
        default=5.0,
        help="Watch-mode sampling period in seconds (default: 5)",
    )
    p.add_argument(
        "--df-every-s",
        type=float,
        default=300.0,
        help="How often to include slower data-flash snapshots in watch mode (default: 300)",
    )
    p.add_argument(
        "--log-csv",
        type=Path,
        default=None,
        help="Optional path for CSV time-series log",
    )
    p.add_argument(
        "--log-jsonl",
        type=Path,
        default=None,
        help="Optional path for JSONL payload log",
    )
    return p


def _field_int(data_flash_fields: dict[str, Any] | None, name: str) -> int | None:
    if data_flash_fields is None:
        return None
    item = data_flash_fields.get(name)
    return None if item is None else int(item["value_int"])


def _collect_payload(
    args: argparse.Namespace,
    *,
    include_df_snapshot: bool = False,
    include_df_blocks: bool = False,
) -> dict[str, Any]:
    base_payload: dict[str, Any] = {
        "chip": "bq34z100",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "i2c": {
            "bus": args.bus,
            "address": f"0x{args.address:02X}",
        },
        "read_options": {
            "configured_rsense_mohm": args.configured_rsense_mohm,
            "actual_rsense_mohm": args.actual_rsense_mohm,
            "swap_word_bytes": bool(args.swap_word_bytes),
            "include_block_dump": bool(args.include_block_dump),
        },
    }

    gauge = BQ34Z100R2(bus_num=args.bus, address=args.address)
    section_errors: dict[str, str] = {}

    telemetry_out: dict[str, Any] | None = None
    control_info: dict[str, Any] | None = None
    data_flash_fields: dict[str, Any] | None = None
    raw_standard_registers: dict[str, Any] | None = None
    data_flash_blocks: list[dict[str, Any]] | None = None
    learning_thresholds: dict[str, int] | None = None

    try:
        telemetry = get_battery_data(
            bus=args.bus,
            address=args.address,
            configured_rsense_mohm=args.configured_rsense_mohm,
            actual_rsense_mohm=args.actual_rsense_mohm,
            swap_word_bytes=args.swap_word_bytes,
        )
        telemetry_out = {
            "voltage": round(float(telemetry.voltage), 3),
            "current_a": round(float(telemetry.current_a), 3),
            "remaining_capacity_ah": round(float(telemetry.remaining_capacity_ah), 3),
            "max_capacity_ah": round(float(telemetry.max_capacity_ah), 3),
            "state_of_charge": int(telemetry.state_of_charge),
            "max_error": int(telemetry.max_error),
        }
    except Exception as exc:  # noqa: BLE001
        section_errors["telemetry"] = str(exc)

    try:
        raw_standard_registers = _read_raw_standard_registers(
            gauge,
            swap_word_bytes=args.swap_word_bytes,
        )
    except Exception as exc:  # noqa: BLE001
        section_errors["raw_standard_registers"] = str(exc)

    try:
        control_info = _read_control_info(gauge)
    except Exception as exc:  # noqa: BLE001
        section_errors["control_info"] = str(exc)

    try:
        data_flash_fields = _read_data_flash_fields(gauge)
    except Exception as exc:  # noqa: BLE001
        section_errors["data_flash_fields"] = str(exc)

    try:
        learning_thresholds = _read_learning_thresholds(gauge)
    except Exception as exc:  # noqa: BLE001
        section_errors["learning_thresholds"] = str(exc)

    if include_df_blocks and args.include_block_dump:
        try:
            data_flash_blocks = _read_data_flash_blocks(gauge)
        except Exception as exc:  # noqa: BLE001
            section_errors["data_flash_blocks"] = str(exc)

    if args.full:
        payload: dict[str, Any] = dict(base_payload)
        if telemetry_out is not None:
            payload["telemetry"] = telemetry_out
        if raw_standard_registers is not None:
            payload["raw_standard_registers"] = raw_standard_registers
        if control_info is not None:
            payload["control_info"] = control_info
        if data_flash_fields is not None:
            payload["data_flash_fields"] = data_flash_fields
        if learning_thresholds is not None:
            payload["learning_thresholds"] = learning_thresholds
        if data_flash_blocks is not None:
            payload["data_flash_blocks"] = data_flash_blocks
    else:
        summary: dict[str, Any] = dict(base_payload)
        if telemetry_out is not None:
            summary["telemetry"] = telemetry_out

        pack_summary: dict[str, Any] = {}
        pack_cfg = _field_int(data_flash_fields, "pack_configuration")
        if pack_cfg is not None:
            msb = (pack_cfg >> 8) & 0xFF
            pack_summary["pack_configuration"] = f"0x{pack_cfg:04X}"
            pack_summary["voltsel_enabled"] = bool(msb & (1 << 3))
        series_cells = _field_int(data_flash_fields, "number_of_series_cells")
        if series_cells is not None:
            pack_summary["series_cells"] = series_cells
        voltage_divider = _field_int(data_flash_fields, "voltage_divider")
        if voltage_divider is not None:
            pack_summary["voltage_divider"] = voltage_divider
        update_status = _field_int(data_flash_fields, "update_status")
        if update_status is not None:
            pack_summary["update_status"] = f"0x{update_status:02X}"
        design_capacity = _field_int(data_flash_fields, "design_capacity_mah")
        if design_capacity is not None:
            pack_summary["design_capacity_mah"] = design_capacity
        qmax = _field_int(data_flash_fields, "qmax_cell0_mah")
        if qmax is not None:
            pack_summary["qmax_cell0_mah"] = qmax

        if control_info is not None:
            summary["chip_info"] = {
                "device_type": control_info["device_type"]["hex"],
                "fw_version": control_info["fw_version"]["hex"],
                "chem_id": control_info["chem_id"]["hex"],
                "control_status": control_info["control_status"]["hex"],
            }

        control_flags: dict[str, Any] = {}
        if control_info is not None:
            control_status_int = int(control_info["control_status"]["int"])
            control_flags.update(_decode_control_status_flags(control_status_int))
            control_flags["CONTROL_STATUS_hex"] = control_info["control_status"]["hex"]
        if raw_standard_registers is not None:
            flags_word = int(raw_standard_registers["flags_raw"]["normalized_word"]["int"])
            control_flags.update(_decode_operation_flags(flags_word))
            control_flags["FLAGS_hex"] = raw_standard_registers["flags_raw"]["normalized_word"]["hex"]
        if control_flags:
            summary["control_flags"] = control_flags

        if pack_summary:
            summary["pack"] = pack_summary

        if raw_standard_registers is not None:
            summary["raw_current_ma_signed"] = raw_standard_registers["average_current_ma_raw"]["normalized_signed"]

        learning_summary: dict[str, Any] = {}
        taper_current_ma = _field_int(data_flash_fields, "taper_current_ma")
        charge_cell_mv = _field_int(data_flash_fields, "cell_charge_voltage_t2_t3_mv")

        if taper_current_ma is not None:
            learning_summary["taper_current_ma"] = taper_current_ma
        if series_cells is not None:
            learning_summary["series_cells"] = series_cells
        if charge_cell_mv is not None:
            learning_summary["charge_voltage_per_cell_mv"] = charge_cell_mv
        if series_cells is not None and charge_cell_mv is not None:
            charge_target_mv = series_cells * charge_cell_mv
            learning_summary["charge_voltage_target_mv"] = charge_target_mv
            learning_summary["charge_voltage_window_mv"] = [charge_target_mv - 100, charge_target_mv + 100]

        if learning_thresholds is not None:
            learning_summary.update(learning_thresholds)

        current_now_ma: int | None = None
        voltage_now_mv: int | None = None
        if raw_standard_registers is not None:
            current_now_ma = int(raw_standard_registers["average_current_ma_raw"]["normalized_signed"])
            learning_summary["current_now_ma"] = current_now_ma
        if telemetry_out is not None:
            voltage_now_mv = int(round(float(telemetry_out["voltage"]) * 1000.0))
            learning_summary["voltage_now_mv"] = voltage_now_mv

        charge_target_mv = learning_summary.get("charge_voltage_target_mv")
        quit_current_ma = learning_summary.get("quit_current_ma")

        if charge_target_mv is not None and voltage_now_mv is not None:
            learning_summary["voltage_within_100mv"] = abs(int(voltage_now_mv) - int(charge_target_mv)) <= 100
        if taper_current_ma is not None and current_now_ma is not None:
            learning_summary["current_below_taper"] = int(current_now_ma) < int(taper_current_ma)
        if quit_current_ma is not None and current_now_ma is not None:
            learning_summary["current_above_quit"] = int(current_now_ma) > int(quit_current_ma)

        if all(k in learning_summary for k in ("voltage_within_100mv", "current_below_taper", "current_above_quit")):
            fc_now = bool(
                learning_summary["voltage_within_100mv"]
                and learning_summary["current_below_taper"]
                and learning_summary["current_above_quit"]
            )
            learning_summary["fc_conditions_now"] = fc_now
            learning_summary["fc_conditions_now_source"] = "derived"

        if learning_summary:
            summary["learning"] = learning_summary

        if include_df_snapshot and data_flash_fields is not None:
            summary["df_snapshot"] = {
                "data_flash_fields": data_flash_fields,
                "data_flash_blocks": data_flash_blocks if data_flash_blocks is not None else [],
            }

        payload = summary

    if section_errors:
        payload["errors"] = section_errors
    return payload


CSV_COLUMNS = [
    "timestamp_utc",
    "voltage_v",
    "current_a",
    "soc_pct",
    "fcc_ah",
    "remaining_ah",
    "max_error_pct",
    "update_status_hex",
    "chem_id_hex",
    "control_status_hex",
    "flags_hex",
    "FC",
    "VOK",
    "RUP_DIS",
    "QEN",
    "charge_voltage_target_mv",
    "voltage_now_mv",
    "voltage_within_100mv",
    "taper_current_ma",
    "current_now_ma",
    "current_below_taper",
    "quit_current_ma",
    "current_above_quit",
    "derived_fc_conditions_now",
    "df_snapshot",
    "event_markers",
]


def _extract_log_row(payload: dict[str, Any], *, df_snapshot: bool, event_markers: str) -> dict[str, Any]:
    telemetry = payload.get("telemetry", {})
    learning = payload.get("learning", {})
    pack = payload.get("pack", {})
    chip_info = payload.get("chip_info", {})
    control_flags = payload.get("control_flags", {})
    return {
        "timestamp_utc": payload.get("timestamp_utc"),
        "voltage_v": telemetry.get("voltage"),
        "current_a": telemetry.get("current_a"),
        "soc_pct": telemetry.get("state_of_charge"),
        "fcc_ah": telemetry.get("max_capacity_ah"),
        "remaining_ah": telemetry.get("remaining_capacity_ah"),
        "max_error_pct": telemetry.get("max_error"),
        "update_status_hex": pack.get("update_status"),
        "chem_id_hex": chip_info.get("chem_id"),
        "control_status_hex": control_flags.get("CONTROL_STATUS_hex"),
        "flags_hex": control_flags.get("FLAGS_hex"),
        "FC": control_flags.get("FC"),
        "VOK": control_flags.get("VOK"),
        "RUP_DIS": control_flags.get("RUP_DIS"),
        "QEN": control_flags.get("QEN"),
        "charge_voltage_target_mv": learning.get("charge_voltage_target_mv"),
        "voltage_now_mv": learning.get("voltage_now_mv"),
        "voltage_within_100mv": learning.get("voltage_within_100mv"),
        "taper_current_ma": learning.get("taper_current_ma"),
        "current_now_ma": learning.get("current_now_ma"),
        "current_below_taper": learning.get("current_below_taper"),
        "quit_current_ma": learning.get("quit_current_ma"),
        "current_above_quit": learning.get("current_above_quit"),
        "derived_fc_conditions_now": learning.get("fc_conditions_now"),
        "df_snapshot": df_snapshot,
        "event_markers": event_markers,
    }


def _transition_events(prev_row: dict[str, Any] | None, row: dict[str, Any]) -> list[str]:
    if prev_row is None:
        return []
    events: list[str] = []
    if prev_row.get("FC") is False and row.get("FC") is True:
        events.append("FC false->true")
    if prev_row.get("VOK") is True and row.get("VOK") is False:
        events.append("VOK true->false")
    if prev_row.get("RUP_DIS") is False and row.get("RUP_DIS") is True:
        events.append("RUP_DIS false->true")
    prev_us = prev_row.get("update_status_hex")
    cur_us = row.get("update_status_hex")
    if prev_us is not None and cur_us is not None and prev_us != cur_us:
        events.append(f"update_status {prev_us}->{cur_us}")
    return events


def _print_watch_line(row: dict[str, Any], events: list[str]) -> None:
    stamp = row.get("timestamp_utc")
    msg = (
        f"[{stamp}] V={row.get('voltage_v')}V I={row.get('current_a')}A SOC={row.get('soc_pct')}% "
        f"US={row.get('update_status_hex')} CID={row.get('chem_id_hex')} FC={row.get('FC')} VOK={row.get('VOK')} "
        f"RUP_DIS={row.get('RUP_DIS')} QEN={row.get('QEN')} "
        f"derived_fc={row.get('derived_fc_conditions_now')}"
    )
    if events:
        msg += f" events={';'.join(events)}"
    print(msg)


def _emit_json(payload: dict[str, Any], *, pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def main() -> int:
    args = _build_parser().parse_args()

    if args.interval_s <= 0:
        raise SystemExit("--interval-s must be > 0")
    if args.df_every_s <= 0:
        raise SystemExit("--df-every-s must be > 0")

    if not args.watch:
        payload = _collect_payload(
            args,
            include_df_snapshot=False,
            include_df_blocks=args.full and args.include_block_dump,
        )
        _emit_json(payload, pretty=bool(args.pretty))
        return 0

    if args.log_csv is not None:
        args.log_csv.parent.mkdir(parents=True, exist_ok=True)
    if args.log_jsonl is not None:
        args.log_jsonl.parent.mkdir(parents=True, exist_ok=True)

    csv_file = open(args.log_csv, "a", newline="", encoding="utf-8") if args.log_csv is not None else None
    jsonl_file = open(args.log_jsonl, "a", encoding="utf-8") if args.log_jsonl is not None else None
    csv_writer: csv.DictWriter | None = None
    if csv_file is not None:
        csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        if csv_file.tell() == 0:
            csv_writer.writeheader()
            csv_file.flush()

    prev_row: dict[str, Any] | None = None
    last_df_snapshot_monotonic = 0.0
    try:
        while True:
            now_mono = time.monotonic()
            include_df_snapshot = (now_mono - last_df_snapshot_monotonic) >= float(args.df_every_s)
            payload = _collect_payload(
                args,
                include_df_snapshot=include_df_snapshot,
                include_df_blocks=include_df_snapshot and args.include_block_dump,
            )
            if include_df_snapshot:
                last_df_snapshot_monotonic = now_mono

            row = _extract_log_row(payload, df_snapshot=include_df_snapshot, event_markers="")
            events = _transition_events(prev_row, row)
            event_markers = ";".join(events)
            row["event_markers"] = event_markers

            _print_watch_line(row, events)

            if csv_writer is not None and csv_file is not None:
                csv_writer.writerow(row)
                csv_file.flush()
            if jsonl_file is not None:
                jsonl_file.write(json.dumps(payload, sort_keys=True) + "\n")
                jsonl_file.flush()

            prev_row = row
            time.sleep(float(args.interval_s))
    except KeyboardInterrupt:
        print("Stopped watch mode.")
    finally:
        if csv_file is not None:
            csv_file.close()
        if jsonl_file is not None:
            jsonl_file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

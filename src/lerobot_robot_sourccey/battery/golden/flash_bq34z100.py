#!/usr/bin/env python3
"""Program a bq34z100 gauge from TI FlashStream files (.bq.fs / .df.fs).

Supports the standard TI FlashStream line types:
- ``W:`` write bytes to I2C address + register
- ``C:`` read and compare bytes from I2C address + register
- ``X:`` delay in milliseconds
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


THIS_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILE_FILES: dict[str, Path] = {
    "df": THIS_DIR / "0100_2_01-bq34z100.df.fs",
    "bq": THIS_DIR / "0100_2_01-bq34z100.bq.fs",
}


@dataclass(frozen=True)
class FlashstreamCommand:
    line_no: int
    kind: str
    address8: int | None
    register: int | None
    payload: bytes
    delay_ms: int | None


@dataclass(frozen=True)
class FlashstreamStats:
    file: str
    commands_total: int
    writes: int
    compares: int
    delays: int
    elapsed_s: float


class FlashstreamError(RuntimeError):
    """Raised for parsing or execution failures."""


def _parse_hex_byte(token: str, *, line_no: int) -> int:
    try:
        value = int(token, 16)
    except ValueError as exc:
        raise FlashstreamError(f"Line {line_no}: invalid hex byte {token!r}") from exc
    if value < 0 or value > 0xFF:
        raise FlashstreamError(f"Line {line_no}: byte out of range {token!r}")
    return value


def parse_flashstream(path: Path) -> list[FlashstreamCommand]:
    commands: list[FlashstreamCommand] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise FlashstreamError(f"Line {line_no}: expected '<cmd>: ...', got {raw!r}")

        kind, rest = line.split(":", 1)
        kind = kind.strip().upper()
        rest = rest.strip()

        if kind == "X":
            try:
                delay_ms = int(rest, 0)
            except ValueError as exc:
                raise FlashstreamError(f"Line {line_no}: invalid delay {rest!r}") from exc
            if delay_ms < 0:
                raise FlashstreamError(f"Line {line_no}: delay must be >= 0")
            commands.append(
                FlashstreamCommand(
                    line_no=line_no,
                    kind=kind,
                    address8=None,
                    register=None,
                    payload=b"",
                    delay_ms=delay_ms,
                )
            )
            continue

        if kind not in {"W", "C"}:
            raise FlashstreamError(f"Line {line_no}: unsupported command {kind!r}")

        tokens = rest.split()
        if len(tokens) < 2:
            raise FlashstreamError(f"Line {line_no}: expected at least i2cAddr + RegAddr")
        raw_bytes = [_parse_hex_byte(tok, line_no=line_no) for tok in tokens]
        commands.append(
            FlashstreamCommand(
                line_no=line_no,
                kind=kind,
                address8=raw_bytes[0],
                register=raw_bytes[1],
                payload=bytes(raw_bytes[2:]),
                delay_ms=None,
            )
        )

    if not commands:
        raise FlashstreamError(f"No flashstream commands found in {path}")
    return commands


def _normalize_7bit_address(address8: int) -> int:
    return (address8 >> 1) & 0x7F


def _open_bus(bus_num: int) -> Any:
    try:
        from smbus2 import SMBus
    except ImportError as exc:
        raise SystemExit("smbus2 is required. Install with: pip install smbus2") from exc
    return SMBus(bus_num)


def run_flashstream_file(
    *,
    fs_file: Path,
    bus: int = 1,
    dry_run: bool = False,
    strict_compare: bool = True,
    progress_every: int = 200,
    quiet: bool = False,
) -> FlashstreamStats:
    commands = parse_flashstream(fs_file)

    writes = 0
    compares = 0
    delays = 0
    started = time.monotonic()

    if progress_every <= 0:
        progress_every = 0

    if not quiet:
        print(
            f"Flashstream start: file={fs_file}, bus={bus}, commands={len(commands)}, "
            f"dry_run={dry_run}, strict_compare={strict_compare}"
        )

    if dry_run:
        for idx, cmd in enumerate(commands, start=1):
            if cmd.kind == "W":
                writes += 1
            elif cmd.kind == "C":
                compares += 1
            elif cmd.kind == "X":
                delays += 1
            if progress_every and (idx % progress_every == 0 or idx == len(commands)):
                print(f"Dry-run progress: {idx}/{len(commands)} commands")
        elapsed = time.monotonic() - started
        return FlashstreamStats(
            file=str(fs_file),
            commands_total=len(commands),
            writes=writes,
            compares=compares,
            delays=delays,
            elapsed_s=elapsed,
        )

    try:
        from smbus2 import i2c_msg
    except ImportError as exc:
        raise SystemExit("smbus2 is required. Install with: pip install smbus2") from exc

    with _open_bus(bus) as smbus:
        for idx, cmd in enumerate(commands, start=1):
            if cmd.kind == "X":
                delays += 1
                time.sleep(float(cmd.delay_ms or 0) / 1000.0)
            elif cmd.kind == "W":
                writes += 1
                assert cmd.address8 is not None and cmd.register is not None
                address7 = _normalize_7bit_address(cmd.address8)
                payload = bytes([cmd.register]) + cmd.payload
                smbus.i2c_rdwr(i2c_msg.write(address7, payload))
            elif cmd.kind == "C":
                compares += 1
                assert cmd.address8 is not None and cmd.register is not None
                address7 = _normalize_7bit_address(cmd.address8)
                expected = cmd.payload
                write_msg = i2c_msg.write(address7, [cmd.register])
                read_msg = i2c_msg.read(address7, len(expected))
                smbus.i2c_rdwr(write_msg, read_msg)
                actual = bytes(read_msg)
                if actual != expected:
                    msg = (
                        f"Line {cmd.line_no}: compare mismatch at addr8=0x{cmd.address8:02X} "
                        f"reg=0x{cmd.register:02X}; expected={expected.hex().upper()} "
                        f"actual={actual.hex().upper()}"
                    )
                    if strict_compare:
                        raise FlashstreamError(msg)
                    print(f"WARNING: {msg}")
            else:
                raise FlashstreamError(f"Line {cmd.line_no}: unknown command kind {cmd.kind!r}")

            if progress_every and (idx % progress_every == 0 or idx == len(commands)):
                print(f"Progress: {idx}/{len(commands)} commands")

    elapsed = time.monotonic() - started
    if not quiet:
        print(f"Flashstream complete in {elapsed:.1f}s")
    return FlashstreamStats(
        file=str(fs_file),
        commands_total=len(commands),
        writes=writes,
        compares=compares,
        delays=delays,
        elapsed_s=elapsed,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Flash a bq34z100 from TI FlashStream file (.bq.fs / .df.fs)")
    p.add_argument("--bus", type=int, default=1, help="I2C bus number (default: 1)")
    p.add_argument(
        "--profile",
        choices=sorted(DEFAULT_PROFILE_FILES),
        default="df",
        help="Built-in flashstream profile to use when --file is not provided (default: df)",
    )
    p.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to a .bq.fs or .df.fs file (overrides --profile)",
    )
    p.add_argument("--dry-run", action="store_true", help="Parse and print progress without doing I2C writes")
    p.add_argument(
        "--strict-compare",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stop immediately on compare mismatch (default: enabled)",
    )
    p.add_argument(
        "--progress-every",
        type=int,
        default=200,
        help="Print progress every N commands (0 disables periodic progress)",
    )
    p.add_argument("--quiet", action="store_true", help="Reduce non-progress output")
    return p


def main() -> int:
    args = build_parser().parse_args()
    fs_file = args.file if args.file is not None else DEFAULT_PROFILE_FILES[args.profile]
    if not fs_file.exists():
        raise SystemExit(f"Flashstream file does not exist: {fs_file}")

    stats = run_flashstream_file(
        fs_file=fs_file,
        bus=args.bus,
        dry_run=bool(args.dry_run),
        strict_compare=bool(args.strict_compare),
        progress_every=int(args.progress_every),
        quiet=bool(args.quiet),
    )

    print(
        "Summary: "
        f"commands={stats.commands_total}, writes={stats.writes}, compares={stats.compares}, "
        f"delays={stats.delays}, elapsed_s={stats.elapsed_s:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Post-install setup command for Sourccey robot and desktop profiles."""

from __future__ import annotations

import argparse
from importlib.resources import files
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RULES_DESTINATION = Path("/etc/udev/rules.d/99-sourccey-hardware.rules")


def _status(message: str) -> None:
    print(f"[sourccey-setup] {message}")


def _run(command: list[str], *, dry_run: bool, label: str) -> bool:
    _status(f"{label}: {' '.join(command)}")
    if dry_run:
        return True
    try:
        subprocess.run(command, check=True)
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        _status(f"ERROR: {label} failed: {exc}")
        return False


def _source_setup_script() -> Path | None:
    candidates = (
        Path.cwd() / "setup" / "setup.py",
        Path(__file__).resolve().parents[2] / "setup" / "setup.py",
    )
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve() != Path(__file__).resolve():
            return candidate
    return None


def _install_udev_rules(*, dry_run: bool) -> bool:
    if platform.system() != "Linux" or shutil.which("udevadm") is None:
        _status("Skipping udev rules because udevadm is unavailable.")
        return True

    use_sudo = hasattr(os, "geteuid") and os.geteuid() != 0
    if use_sudo and shutil.which("sudo") is None:
        _status("ERROR: sudo is required to install Sourccey udev rules.")
        return False
    prefix = ["sudo"] if use_sudo else []

    if dry_run:
        _status(f"DRY RUN: install packaged udev rules at {RULES_DESTINATION}")
        return True

    rules = (
        files("lerobot_robot_sourccey")
        .joinpath("setup_data")
        .joinpath("99-sourccey-hardware.rules")
        .read_text(encoding="utf-8")
    )
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, prefix="sourccey-udev-", suffix=".rules"
        ) as handle:
            handle.write(rules)
            temp_path = Path(handle.name)
        commands = (
            prefix + ["install", "-m", "644", str(temp_path), str(RULES_DESTINATION)],
            prefix + ["udevadm", "control", "--reload-rules"],
            prefix + ["udevadm", "trigger"],
        )
        return all(_run(command, dry_run=False, label="Configuring udev") for command in commands)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _battery_command(module: str, args: list[str], *, dry_run: bool, label: str) -> bool:
    return _run([sys.executable, "-m", module, *args], dry_run=dry_run, label=label)


def _verify_battery(*, dry_run: bool) -> bool:
    steps = (
        ("lerobot_robot_sourccey.battery.configure_bq34z100", ["info"], "Checking battery identity"),
        ("lerobot_robot_sourccey.battery.check_bq34z100", ["--pretty"], "Checking battery diagnostics"),
        ("lerobot_robot_sourccey.battery.battery", [], "Checking battery telemetry"),
    )
    return all(_battery_command(module, args, dry_run=dry_run, label=label) for module, args, label in steps)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finish Sourccey setup after package installation")
    parser.add_argument("profile", choices=("robot", "desktop"))
    parser.add_argument("--skip-udev", action="store_true")
    battery = parser.add_mutually_exclusive_group()
    battery.add_argument("--configure-battery", action="store_true")
    battery.add_argument("--flash-battery", choices=("df", "bq"))
    parser.add_argument("--skip-battery-check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _run_installed(args: argparse.Namespace) -> int:
    if args.profile == "desktop":
        _status("Desktop post-install setup complete.")
        return 0
    if platform.system() != "Linux" and not args.dry_run:
        _status("ERROR: the robot profile requires Linux.")
        return 1
    if not args.skip_udev and not _install_udev_rules(dry_run=args.dry_run):
        return 1
    if args.configure_battery and not _battery_command(
        "lerobot_robot_sourccey.battery.configure_bq34z100",
        ["setup-4s-lifepo4"],
        dry_run=args.dry_run,
        label="Applying explicit 4S LiFePO4 battery configuration",
    ):
        return 1
    if args.flash_battery and not _battery_command(
        "lerobot_robot_sourccey.battery.golden.flash_bq34z100",
        ["--profile", args.flash_battery],
        dry_run=args.dry_run,
        label=f"Flashing explicit {args.flash_battery} battery profile",
    ):
        return 1
    if not args.skip_battery_check:
        if Path("/dev/i2c-1").exists() or args.dry_run:
            if not _verify_battery(dry_run=args.dry_run):
                return 1
        else:
            _status("Skipping battery verification because /dev/i2c-1 is unavailable.")
    _status("Robot post-install setup complete. Battery writes require an explicit option.")
    return 0


def main() -> int:
    source_setup = _source_setup_script()
    if source_setup is not None:
        return subprocess.run([sys.executable, str(source_setup), *sys.argv[1:]], check=False).returncode
    return _run_installed(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

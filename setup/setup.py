#!/usr/bin/env python3
"""Bootstrap a robot-host or desktop checkout of lerobot-robot-sourccey."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
from pathlib import Path

from setup_modules.setup_battery import BatterySetup
from setup_modules.setup_udev import configure_sourccey_udev

SUPPORTED_PYTHON_MINORS = {12, 13}
DEFAULT_PYTHON = "3.12"


class SetupScript:
    def __init__(self, project_root: Path, *, dry_run: bool = False):
        self.project_root = project_root
        self.dry_run = dry_run

    @staticmethod
    def print_status(message: str) -> None:
        print(f"[sourccey-setup] {message}")

    @property
    def venv_python(self) -> Path:
        if platform.system() == "Windows":
            return self.project_root / ".venv" / "Scripts" / "python.exe"
        return self.project_root / ".venv" / "bin" / "python"

    def _run(self, command: list[str], label: str) -> bool:
        self.print_status(f"{label}: {' '.join(command)}")
        if self.dry_run:
            return True
        try:
            subprocess.run(command, check=True, cwd=self.project_root)
            return True
        except (OSError, subprocess.CalledProcessError) as exc:
            self.print_status(f"ERROR: {label} failed: {exc}")
            return False

    def validate(self, profile: str) -> bool:
        if not (self.project_root / "pyproject.toml").is_file() or not (
            self.project_root / "src" / "lerobot_robot_sourccey"
        ).is_dir():
            self.print_status(f"ERROR: {self.project_root} is not a lerobot-robot-sourccey checkout.")
            return False
        if shutil.which("uv") is None:
            self.print_status("ERROR: uv is required: https://docs.astral.sh/uv/getting-started/installation/")
            return False
        if profile == "robot" and platform.system() != "Linux" and not self.dry_run:
            self.print_status("ERROR: the robot profile requires Linux.")
            return False
        return True

    def ensure_environment(self, profile: str, python_version: str) -> bool:
        if not self.venv_python.exists():
            if not self._run(["uv", "venv", "--python", python_version], "Creating .venv"):
                return False
        elif not self.dry_run:
            result = subprocess.run(
                [str(self.venv_python), "-c", "import sys; print(sys.version_info.minor)"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )
            if result.returncode != 0 or int(result.stdout.strip()) not in SUPPORTED_PYTHON_MINORS:
                self.print_status("ERROR: existing .venv must use Python 3.12 or 3.13; recreate it explicitly.")
                return False

        return self._run(
            ["uv", "pip", "install", "--python", str(self.venv_python), "-e", f".[{profile}]"],
            f"Installing the {profile} profile",
        )

    @staticmethod
    def is_raspberry_pi() -> bool:
        for candidate in (Path("/proc/device-tree/model"), Path("/sys/firmware/devicetree/base/model")):
            try:
                model = candidate.read_text(encoding="utf-8", errors="ignore").replace("\x00", "").lower()
            except OSError:
                continue
            if "raspberry pi" in model:
                return True
        return False

    def run(
        self,
        *,
        profile: str,
        python_version: str,
        skip_udev: bool,
        battery_action: str | None,
        skip_battery_check: bool,
    ) -> bool:
        if not self.validate(profile) or not self.ensure_environment(profile, python_version):
            return False

        if profile == "desktop":
            self.print_status("Desktop setup complete.")
            return True

        if not skip_udev:
            if self.is_raspberry_pi() or self.dry_run:
                if not configure_sourccey_udev(print_status=self.print_status, dry_run=self.dry_run):
                    return False
            else:
                self.print_status("Skipping udev rules because this Linux host is not detected as a Raspberry Pi.")

        battery = BatterySetup(self.venv_python, self.project_root, self.print_status, self.dry_run)
        if battery_action == "configure" and not battery.configure():
            return False
        if battery_action in {"df", "bq"} and not battery.flash(battery_action):
            return False

        i2c_available = Path("/dev/i2c-1").exists()
        if not skip_battery_check and (i2c_available or self.dry_run):
            if not battery.verify():
                return False
        elif not skip_battery_check:
            self.print_status("Skipping battery verification because /dev/i2c-1 is unavailable.")

        self.print_status("Robot setup complete. Battery state was not modified unless explicitly requested.")
        return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Set up lerobot-robot-sourccey from a source checkout")
    parser.add_argument("profile", choices=("robot", "desktop"), help="Machine profile to install")
    parser.add_argument("--python", default=DEFAULT_PYTHON, help="Python version for a new .venv (default: 3.12)")
    parser.add_argument("--skip-udev", action="store_true", help="Do not install robot hardware aliases")
    battery = parser.add_mutually_exclusive_group()
    battery.add_argument(
        "--configure-battery",
        action="store_true",
        help="Explicitly write the Sourccey 4S LiFePO4 starter configuration",
    )
    battery.add_argument(
        "--flash-battery",
        choices=("df", "bq"),
        help="Explicitly flash the selected built-in golden profile",
    )
    parser.add_argument("--skip-battery-check", action="store_true", help="Skip read-only battery verification")
    parser.add_argument("--dry-run", action="store_true", help="Print planned operations without changing anything")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project_root = Path(__file__).resolve().parent.parent
    battery_action = "configure" if args.configure_battery else args.flash_battery
    success = SetupScript(project_root, dry_run=args.dry_run).run(
        profile=args.profile,
        python_version=args.python,
        skip_udev=args.skip_udev,
        battery_action=battery_action,
        skip_battery_check=args.skip_battery_check,
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

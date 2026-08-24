"""Safe, opt-in battery setup helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

PrintFn = Callable[[str], None]


class BatterySetup:
    """Run packaged BQ34Z100 commands through the project interpreter."""

    def __init__(self, python_path: Path, project_root: Path, print_status: PrintFn, dry_run: bool = False):
        self.python_path = python_path
        self.project_root = project_root
        self.print_status = print_status
        self.dry_run = dry_run

    def _run(self, module: str, args: list[str], label: str) -> bool:
        command = [str(self.python_path), "-m", module, *args]
        self.print_status(f"{label}: {' '.join(command)}")
        if self.dry_run:
            return True
        try:
            subprocess.run(command, check=True, cwd=self.project_root)
            return True
        except (OSError, subprocess.CalledProcessError) as exc:
            self.print_status(f"ERROR: {label} failed: {exc}")
            return False

    def configure(self) -> bool:
        return self._run(
            "lerobot_robot_sourccey.battery.configure_bq34z100",
            ["setup-4s-lifepo4"],
            "Applying explicit 4S LiFePO4 configuration",
        )

    def flash(self, profile: str) -> bool:
        return self._run(
            "lerobot_robot_sourccey.battery.golden.flash_bq34z100",
            ["--profile", profile],
            f"Flashing explicit BQ34Z100 {profile} profile",
        )

    def verify(self) -> bool:
        steps = (
            (
                "lerobot_robot_sourccey.battery.configure_bq34z100",
                ["info"],
                "Checking BQ34Z100 identity",
            ),
            (
                "lerobot_robot_sourccey.battery.check_bq34z100",
                ["--pretty"],
                "Collecting BQ34Z100 diagnostics",
            ),
            (
                "lerobot_robot_sourccey.battery.battery",
                [],
                "Reading battery telemetry",
            ),
        )
        return all(self._run(module, args, label) for module, args, label in steps)

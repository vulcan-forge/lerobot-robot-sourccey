"""Install persistent Sourccey hardware aliases on Raspberry Pi."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

PrintFn = Callable[[str], None]

RULES_FILE_PATH = Path("/etc/udev/rules.d/99-sourccey-hardware.rules")
RULES_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "lerobot_robot_sourccey"
    / "setup_data"
    / "99-sourccey-hardware.rules"
)

EXPECTED_DEVICE_ALIASES = (
    "/dev/robotLeftArm",
    "/dev/robotRightArm",
    "/dev/cameraFrontLeft",
    "/dev/cameraFrontRight",
    "/dev/cameraWristLeft",
    "/dev/cameraWristRight",
    "/dev/cameraFrontBottom",
    "/dev/lidarFront",
)


def configure_sourccey_udev(*, print_status: PrintFn, dry_run: bool = False) -> bool:
    """Install the packaged Sourccey udev rules and reload udev."""
    if os.name == "nt" or shutil.which("udevadm") is None:
        print_status("Skipping udev rules: udevadm is unavailable on this system.")
        return True

    use_sudo = hasattr(os, "geteuid") and os.geteuid() != 0
    if use_sudo and shutil.which("sudo") is None:
        print_status("ERROR: sudo is required to install Sourccey udev rules.")
        return False

    prefix = ["sudo"] if use_sudo else []
    if dry_run:
        print_status(f"DRY RUN: install Sourccey udev rules at {RULES_FILE_PATH}")
        return True

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, prefix="sourccey-udev-", suffix=".rules"
        ) as handle:
            handle.write(RULES_SOURCE_PATH.read_text(encoding="utf-8"))
            temp_path = Path(handle.name)

        subprocess.run(prefix + ["install", "-m", "644", str(temp_path), str(RULES_FILE_PATH)], check=True)
        subprocess.run(prefix + ["udevadm", "control", "--reload-rules"], check=True)
        subprocess.run(prefix + ["udevadm", "trigger"], check=True)
        print_status("Installed Sourccey aliases: " + ", ".join(EXPECTED_DEVICE_ALIASES))
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        print_status(f"ERROR: failed to install udev rules: {exc}")
        return False
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

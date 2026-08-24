from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = PROJECT_ROOT / "setup" / "setup.py"


def run_setup(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SETUP_SCRIPT), *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )


def test_desktop_setup_dry_run_uses_desktop_profile() -> None:
    result = run_setup("desktop", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert ".[desktop]" in result.stdout
    assert "Desktop setup complete" in result.stdout


def test_robot_setup_dry_run_does_not_write_battery_by_default() -> None:
    result = run_setup("robot", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert ".[robot]" in result.stdout
    assert "setup-4s-lifepo4" not in result.stdout
    assert "--profile df" not in result.stdout
    assert "--profile bq" not in result.stdout


def test_robot_setup_requires_explicit_flash_profile() -> None:
    result = run_setup("robot", "--dry-run", "--flash-battery", "bq")
    assert result.returncode == 0, result.stderr
    assert "flash_bq34z100 --profile bq" in result.stdout


def test_battery_write_modes_are_mutually_exclusive() -> None:
    result = run_setup(
        "robot",
        "--dry-run",
        "--configure-battery",
        "--flash-battery",
        "df",
    )
    assert result.returncode != 0
    assert "not allowed with argument" in result.stderr

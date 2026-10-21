#!/usr/bin/env python

# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Sourccey-owned retry wrapper for upstream LeRobot training.

This script forwards all unknown CLI args to ``lerobot_train.py``.
If training exits with a non-zero code, it retries from:
``<output_dir>/checkpoints/last/pretrained_model/train_config.json``.
"""

import argparse
import json
import logging
import shlex
import subprocess
import sys
import time
from pathlib import Path

import yaml

from lerobot.utils.import_utils import register_third_party_plugins

_LAST_TRAIN_CONFIG_RELATIVE = Path("checkpoints/last/pretrained_model/train_config.json")


def _extract_output_dir(train_args: list[str]) -> Path | None:
    """Extract output_dir from CLI args, falling back to the YAML/JSON config."""
    for index, arg in enumerate(train_args):
        if arg.startswith("--output_dir="):
            return Path(arg.split("=", 1)[1]).expanduser()

        if arg in ("--output_dir", "--output-dir") and index + 1 < len(train_args):
            return Path(train_args[index + 1]).expanduser()

    config_path: Path | None = None
    for index, arg in enumerate(train_args):
        if arg.startswith(("--config_path=", "--config-path=")):
            config_path = Path(arg.split("=", 1)[1]).expanduser()
            break
        if arg in ("--config_path", "--config-path") and index + 1 < len(train_args):
            config_path = Path(train_args[index + 1]).expanduser()
            break
    if config_path is None or not config_path.is_file():
        return None
    with config_path.open(encoding="utf-8") as config_file:
        config = (
            json.load(config_file) if config_path.suffix.lower() == ".json" else yaml.safe_load(config_file)
        )
    if isinstance(config, dict) and config.get("output_dir"):
        return Path(config["output_dir"]).expanduser()
    return None


def _drop_args(train_args: list[str], flags: tuple[str, ...]) -> list[str]:
    """Remove flag forms '--flag value' and '--flag=value' from train args."""
    filtered: list[str] = []
    skip_next = False

    for arg in train_args:
        if skip_next:
            skip_next = False
            continue

        if arg in flags:
            skip_next = True
            continue

        if any(arg.startswith(f"{flag}=") for flag in flags):
            continue

        filtered.append(arg)

    return filtered


def _build_resume_args(train_args: list[str], config_path: Path) -> list[str]:
    sanitized_args = _drop_args(
        train_args,
        ("--resume", "--config_path", "--config-path", "--policy.path", "--policy-path"),
    )
    return [*sanitized_args, "--resume=true", f"--config_path={config_path}"]


def _run_training_module(train_args: list[str], training_module: str) -> int:
    # Run as a module so relative imports inside lerobot_train.py resolve correctly.
    cmd = [sys.executable, "-m", training_module, *train_args]
    logging.info("Launching command: %s", shlex.join(cmd))
    return subprocess.run(cmd, check=False).returncode


def retry_main(
    training_module: str = "lerobot.scripts.lerobot_train",
    training_name: str = "lerobot_train.py",
) -> int:
    """Run training with bounded retries from the last resumable checkpoint."""
    register_third_party_plugins()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)

    parser = argparse.ArgumentParser(
        description=f"Run {training_name} with auto-retry and automatic resume from the last checkpoint.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=10,
        help="Maximum total attempts (initial run included).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Maximum retries after the initial attempt. Overrides --max-attempts when set.",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=20.0,
        help="Delay before retrying after a failed attempt.",
    )

    args, train_args = parser.parse_known_args()

    if args.max_attempts < 1:
        parser.error("--max-attempts must be >= 1")

    if args.max_retries is not None and args.max_retries < 0:
        parser.error("--max-retries must be >= 0")

    if args.retry_delay_seconds < 0:
        parser.error("--retry-delay-seconds must be >= 0")

    if not train_args:
        parser.error("No training arguments were provided.")

    max_attempts = args.max_attempts if args.max_retries is None else (args.max_retries + 1)

    output_dir = _extract_output_dir(train_args)
    if output_dir is None:
        parser.error("Missing output_dir in the CLI arguments or training config. It is required for resume.")

    resume_config_path = output_dir / _LAST_TRAIN_CONFIG_RELATIVE
    retry_train_args = train_args

    for attempt in range(1, max_attempts + 1):
        logging.info("Starting training attempt %d/%d", attempt, max_attempts)
        exit_code = _run_training_module(retry_train_args, training_module)

        if exit_code == 0:
            logging.info("Training finished successfully on attempt %d.", attempt)
            return 0

        if attempt >= max_attempts:
            logging.error(
                "Training failed on attempt %d/%d with exit code %d.",
                attempt,
                max_attempts,
                exit_code,
            )
            return exit_code

        if not resume_config_path.exists():
            logging.error(
                "Training failed with exit code %d and resume config was not found at: %s",
                exit_code,
                resume_config_path,
            )
            logging.error("Cannot retry safely because no resumable checkpoint is available.")
            return exit_code

        retry_train_args = _build_resume_args(train_args, resume_config_path)
        logging.warning(
            "Attempt %d failed with exit code %d. Retrying in %.1f seconds using %s",
            attempt,
            exit_code,
            args.retry_delay_seconds,
            resume_config_path,
        )
        if args.retry_delay_seconds > 0:
            time.sleep(args.retry_delay_seconds)

    return 1


def main() -> int:
    """Run the Sourccey training-retry command."""
    return retry_main()


if __name__ == "__main__":
    raise SystemExit(main())

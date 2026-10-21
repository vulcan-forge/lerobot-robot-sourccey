#!/usr/bin/env python

# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
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

"""Check retry argument handling and checkpoint-driven training restarts."""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from lerobot_robot_sourccey.train_retry import _build_resume_args, _extract_output_dir


def test_build_resume_args_drops_policy_path_flags() -> None:
    """Resume from checkpoint configuration rather than the initial pretrained policy."""
    train_args = [
        "--dataset.repo_id=dummy/repo",
        "--output_dir=outputs/train/test-run",
        "--policy.path=lerobot/xvla-base",
        "--resume=false",
    ]

    resume_args = _build_resume_args(
        train_args, Path("outputs/train/test-run/checkpoints/last/pretrained_model/train_config.json")
    )

    assert all(not arg.startswith("--policy.path") for arg in resume_args)
    assert "--resume=true" in resume_args
    assert any(arg.startswith("--config_path=") for arg in resume_args)


def test_extract_output_dir_from_yaml_config(tmp_path: Path) -> None:
    """Find the checkpoint output directory in a YAML training configuration."""
    config_path = tmp_path / "train.yaml"
    config_path.write_text("output_dir: outputs/train/example\n", encoding="utf-8")

    assert _extract_output_dir([f"--config_path={config_path}"]) == Path("outputs/train/example")


def test_cli_output_dir_overrides_yaml_config(tmp_path: Path) -> None:
    """Give an explicit command-line output directory priority over YAML."""
    config_path = tmp_path / "train.yaml"
    config_path.write_text("output_dir: outputs/train/from-config\n", encoding="utf-8")

    assert _extract_output_dir(
        [f"--config_path={config_path}", "--output_dir=outputs/train/from-cli"]
    ) == Path("outputs/train/from-cli")


def test_retry_resumes_from_checkpoint_and_drops_initial_policy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry a failed run through upstream training using the last saved checkpoint."""
    import lerobot_robot_sourccey.train_retry as retry

    config_path = tmp_path / "checkpoints/last/pretrained_model/train_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{}")
    calls = []

    def run_training(args: list[str], training_module: str) -> int:
        calls.append((list(args), training_module))
        return 1 if len(calls) == 1 else 0

    monkeypatch.setattr(retry, "register_third_party_plugins", lambda: None)
    monkeypatch.setattr(retry, "_run_training_module", run_training)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sourccey-train-retry",
            "--max-attempts=2",
            "--retry-delay-seconds=0",
            f"--output_dir={tmp_path}",
            "--policy.path=lerobot/xvla-base",
        ],
    )

    assert retry.main() == 0
    assert len(calls) == 2
    assert "--policy.path=lerobot/xvla-base" in calls[0][0]
    assert "--policy.path=lerobot/xvla-base" not in calls[1][0]
    assert "--resume=true" in calls[1][0]
    assert f"--config_path={config_path}" in calls[1][0]
    assert all(module == "lerobot.scripts.lerobot_train" for _, module in calls)


def test_retry_stops_when_no_resumable_checkpoint_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Return the training failure code when a checkpoint cannot support a retry."""
    import lerobot_robot_sourccey.train_retry as retry

    run_training = Mock(return_value=7)
    monkeypatch.setattr(retry, "register_third_party_plugins", lambda: None)
    monkeypatch.setattr(retry, "_run_training_module", run_training)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lerobot-train-retry",
            "--max-attempts=2",
            "--retry-delay-seconds=0",
            f"--output_dir={tmp_path}",
            "--policy.type=act",
        ],
    )

    assert retry.main() == 7
    assert run_training.call_count == 1

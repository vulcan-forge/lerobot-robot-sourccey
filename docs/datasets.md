# Sourccey datasets: combine, audit, repair, and clean

Use this runbook when you want a clean local dataset for training.

## Prerequisites

From the package checkout, install the dataset tooling:

```bash
uv sync --extra dataset
```

The video-repair shell script also requires `bash`, `ffmpeg`, and `ffprobe`.

## 0) Set your dataset name once

```bash
HF_LEROBOT_HOME="${HOME}/.cache/huggingface/lerobot"
DATASET_REPO="Combination/sourccey-shirt-fold-c-010"
DATASET_ROOT="${HF_LEROBOT_HOME}/${DATASET_REPO}"
STAMP="$(date +%Y%m%d_%H%M%S)"

SAFE_DATASET_REPO="${DATASET_REPO//\//__}"
AUDIT_DIR="outputs/video_audit_${STAMP}_full"
BAD_FILES_TXT="${AUDIT_DIR}/${SAFE_DATASET_REPO}_bad_files.txt"
ISSUES_JSON="${AUDIT_DIR}/${SAFE_DATASET_REPO}_decode_issues.json"
```

## 1) Combine datasets

If per-merge stripping feels too slow, pre-strip once:

```bash
uv run sourccey-dataset-remove-feature \
  --feature intervention \
  --out-parent "${HF_LEROBOT_HOME}/Prepared/no_intervention" \
  --dry-run

uv run sourccey-dataset-remove-feature \
  --feature intervention \
  --out-parent "${HF_LEROBOT_HOME}/Prepared/no_intervention"
```

Then combine from that prepared folder:


Preview what will be merged:

```bash
uv run sourccey-dataset-combine --list-only
```

Run merge:
```bash
uv run sourccey-dataset-combine
```

## 2) Quick sanity check

```bash
uv run lerobot-edit-dataset \
  --repo_id "$DATASET_REPO" \
  --root "$DATASET_ROOT" \
  --operation.type info \
  --operation.show_features true
```

## 3) Audit video decode health

Dataset consistency audit (stats mismatch, intervention leakage, z.pos checks):

```bash
uv run sourccey-dataset-audit-consistency \
  --dataset-root "$DATASET_ROOT"
```

Fail fast version (use in CI / strict checks):

```bash
uv run sourccey-dataset-audit-consistency \
  --dataset-root "$DATASET_ROOT" \
  --fail-on-issues
```

If consistency issues are reported, fix them with:

Dry run:

```bash
uv run sourccey-dataset-fix-consistency \
  --dataset-root "$DATASET_ROOT" \
  --dry-run
```

Apply fixes:

```bash
uv run sourccey-dataset-fix-consistency \
  --dataset-root "$DATASET_ROOT"
```

Fast smoke test:

```bash
uv run sourccey-dataset-audit-videos \
  --dataset-repo-id "$DATASET_REPO" \
  --max-files 1000 \
  --workers 8 \
  --output-dir "outputs/video_audit_${STAMP}_smoke"
```

Full audit:

```bash
uv run sourccey-dataset-audit-videos \
  --dataset-repo-id "$DATASET_REPO" \
  --workers 8 \
  --output-dir "$AUDIT_DIR"
```

Audit outputs:
- `${AUDIT_DIR}/${SAFE_DATASET_REPO}_decode_summary.json`
- `${AUDIT_DIR}/${SAFE_DATASET_REPO}_decode_issues.csv`
- `${AUDIT_DIR}/${SAFE_DATASET_REPO}_bad_files.txt`

## 4) Clean the dataset

### A) Repair bad video files (recommended first)

Dry run:

```bash
bash src/lerobot_robot_sourccey/dataset_tools/repair_bad_videos_from_audit.sh \
  --bad-files-txt "$BAD_FILES_TXT" \
  --dataset-repo-id "$DATASET_REPO" \
  --dry-run
```

Apply repair:

```bash
bash src/lerobot_robot_sourccey/dataset_tools/repair_bad_videos_from_audit.sh \
  --bad-files-txt "$BAD_FILES_TXT" \
  --dataset-repo-id "$DATASET_REPO"
```

Re-audit after repair:

```bash
uv run sourccey-dataset-audit-videos \
  --dataset-repo-id "$DATASET_REPO" \
  --workers 8 \
  --output-dir "outputs/video_audit_${STAMP}_post_repair"
```

### B) Optional: drop episodes linked to decode errors

Build an episode list from audit issues:

```bash
EPISODES_TO_DROP_JSON="${AUDIT_DIR}/${SAFE_DATASET_REPO}_episodes_to_drop_from_decode.json"
export ISSUES_JSON EPISODES_TO_DROP_JSON

uv run python - <<'PY'
import json
import os
from pathlib import Path

issues_path = Path(os.environ["ISSUES_JSON"])
out_path = Path(os.environ["EPISODES_TO_DROP_JSON"])

issues = json.loads(issues_path.read_text())
indices = sorted({int(i) for row in issues for i in row.get("episode_indices_preview", [])})
out_path.write_text(json.dumps(indices))

print(f"Wrote {len(indices)} episode indices to: {out_path}")
PY
```

Create a filtered dataset (keeps original dataset intact):

```bash
FILTERED_REPO="${DATASET_REPO}__drop_bad_episodes"
FILTERED_ROOT="${HF_LEROBOT_HOME}/${FILTERED_REPO}"

uv run lerobot-edit-dataset \
  --repo_id "$DATASET_REPO" \
  --root "$DATASET_ROOT" \
  --new_repo_id "$FILTERED_REPO" \
  --new_root "$FILTERED_ROOT" \
  --operation.type delete_episodes \
  --operation.episode_indices "$(tr -d '\n' < "$EPISODES_TO_DROP_JSON")"
```

## 5) Final check

Run this on the final dataset you plan to train on:

```bash
uv run lerobot-edit-dataset \
  --repo_id "$DATASET_REPO" \
  --root "$DATASET_ROOT" \
  --operation.type info \
  --operation.show_features true
```

If you switched to filtered output, replace with:
- `--repo_id "$FILTERED_REPO"`
- `--root "$FILTERED_ROOT"`

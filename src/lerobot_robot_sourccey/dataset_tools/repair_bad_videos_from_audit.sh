#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Repair bad dataset video files listed in an audit bad-files list.

Usage:
  repair_bad_videos_from_audit.sh \
    --bad-files-txt <path> \
    (--dataset-root <path> | --dataset-repo-id <repo_id>) \
    [--hf-root <path>] \
    [--codec <name>] \
    [--crf <int>] \
    [--preset <int>] \
    [--pix-fmt <name>] \
    [--tag <run_tag>] \
    [--limit <n>] \
    [--continue-on-error] \
    [--dry-run]

Options:
  --bad-files-txt <path>     Path to *_bad_files.txt from the audit script.
  --dataset-root <path>      Dataset root containing meta/, data/, videos/.
  --dataset-repo-id <repo>   Dataset repo id (used with --hf-root to build root).
  --hf-root <path>           Base HF datasets cache root.
                             Default: $HOME/.cache/huggingface/lerobot
  --codec <name>             ffmpeg video codec. Default: libsvtav1
  --crf <int>                ffmpeg CRF. Default: 18
  --preset <int>             ffmpeg preset. Default: 8
  --pix-fmt <name>           ffmpeg pixel format. Default: yuv420p
  --tag <run_tag>            Suffix for backup/fixed files.
                             Default: current timestamp YYYYmmdd_HHMMSS
  --limit <n>                Optional cap on repaired files.
  --continue-on-error        Continue repairing remaining files if one fails.
  --dry-run                  Print intended actions without modifying files.
  -h, --help                 Show this help message.

Examples:
  repair_bad_videos_from_audit.sh \
    --bad-files-txt outputs/video_audit_batch_001/Combination__sourccey-shirt-aggregate-2-hq_bad_files.txt \
    --dataset-repo-id Combination/sourccey-shirt-aggregate-2-hq \
    --dry-run

  repair_bad_videos_from_audit.sh \
    --bad-files-txt outputs/video_audit_batch_001/Combination__sourccey-shirt-aggregate-2-hq_bad_files.txt \
    --dataset-repo-id Combination/sourccey-shirt-aggregate-2-hq
EOF
}

BAD_FILES_TXT=""
DATASET_ROOT=""
DATASET_REPO_ID=""
HF_ROOT="${HOME}/.cache/huggingface/lerobot"
CODEC="libsvtav1"
CRF="18"
PRESET="8"
PIX_FMT="yuv420p"
RUN_TAG="$(date +%Y%m%d_%H%M%S)"
LIMIT=""
DRY_RUN=0
CONTINUE_ON_ERROR=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bad-files-txt)
      BAD_FILES_TXT="$2"
      shift 2
      ;;
    --dataset-root)
      DATASET_ROOT="$2"
      shift 2
      ;;
    --dataset-repo-id)
      DATASET_REPO_ID="$2"
      shift 2
      ;;
    --hf-root)
      HF_ROOT="$2"
      shift 2
      ;;
    --codec)
      CODEC="$2"
      shift 2
      ;;
    --crf)
      CRF="$2"
      shift 2
      ;;
    --preset)
      PRESET="$2"
      shift 2
      ;;
    --pix-fmt)
      PIX_FMT="$2"
      shift 2
      ;;
    --tag)
      RUN_TAG="$2"
      shift 2
      ;;
    --limit)
      LIMIT="$2"
      shift 2
      ;;
    --continue-on-error)
      CONTINUE_ON_ERROR=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$BAD_FILES_TXT" ]]; then
  echo "Missing required argument: --bad-files-txt" >&2
  exit 1
fi

if [[ -z "$DATASET_ROOT" ]]; then
  if [[ -z "$DATASET_REPO_ID" ]]; then
    echo "Provide either --dataset-root or --dataset-repo-id." >&2
    exit 1
  fi
  DATASET_ROOT="${HF_ROOT}/${DATASET_REPO_ID}"
fi

if [[ ! -f "$BAD_FILES_TXT" ]]; then
  echo "bad-files list not found: $BAD_FILES_TXT" >&2
  exit 1
fi

if [[ ! -d "$DATASET_ROOT" ]]; then
  echo "dataset root not found: $DATASET_ROOT" >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required but not found in PATH." >&2
  exit 1
fi

if [[ -n "$LIMIT" ]] && ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "--limit must be a non-negative integer." >&2
  exit 1
fi

echo "bad_files_txt=$BAD_FILES_TXT"
echo "dataset_root=$DATASET_ROOT"
echo "codec=$CODEC crf=$CRF preset=$PRESET pix_fmt=$PIX_FMT"
echo "run_tag=$RUN_TAG dry_run=$DRY_RUN continue_on_error=$CONTINUE_ON_ERROR limit=${LIMIT:-all}"
echo

attempted=0
repaired=0
failed=0
missing=0
dry_run_count=0

while IFS= read -r rel_path || [[ -n "$rel_path" ]]; do
  # Skip empty lines/comments
  [[ -z "$rel_path" ]] && continue
  [[ "${rel_path:0:1}" == "#" ]] && continue

  if [[ -n "$LIMIT" ]] && (( attempted >= LIMIT )); then
    break
  fi

  attempted=$((attempted + 1))
  abs_path="${DATASET_ROOT}/${rel_path}"
  bak_path="${abs_path}.bak_${RUN_TAG}"
  fixed_path="${abs_path}.fixed_${RUN_TAG}.mp4"

  echo "[${attempted}] ${rel_path}"

  if [[ ! -f "$abs_path" ]]; then
    echo "  missing source file: $abs_path" >&2
    missing=$((missing + 1))
    failed=$((failed + 1))
    if (( CONTINUE_ON_ERROR == 0 )); then
      exit 2
    fi
    continue
  fi

  if (( DRY_RUN == 1 )); then
    echo "  cp \"$abs_path\" \"$bak_path\""
    echo "  ffmpeg -nostdin -v warning -fflags +discardcorrupt -err_detect ignore_err -i \"$bak_path\" -an -c:v \"$CODEC\" -crf \"$CRF\" -preset \"$PRESET\" -pix_fmt \"$PIX_FMT\" -y \"$fixed_path\""
    echo "  mv \"$fixed_path\" \"$abs_path\""
    dry_run_count=$((dry_run_count + 1))
    continue
  fi

  if [[ -e "$bak_path" ]]; then
    echo "  backup already exists, refusing to overwrite: $bak_path" >&2
    failed=$((failed + 1))
    if (( CONTINUE_ON_ERROR == 0 )); then
      exit 2
    fi
    continue
  fi

  cp "$abs_path" "$bak_path"
  if ffmpeg -nostdin -v warning -fflags +discardcorrupt -err_detect ignore_err -i "$bak_path" -an -c:v "$CODEC" -crf "$CRF" -preset "$PRESET" -pix_fmt "$PIX_FMT" -y "$fixed_path"; then
    mv "$fixed_path" "$abs_path"
    repaired=$((repaired + 1))
    echo "  repaired"
  else
    echo "  ffmpeg repair failed: $abs_path" >&2
    rm -f "$fixed_path"
    failed=$((failed + 1))
    if (( CONTINUE_ON_ERROR == 0 )); then
      exit 2
    fi
  fi
done < "$BAD_FILES_TXT"

echo
echo "Summary:"
echo "  attempted=${attempted}"
echo "  repaired=${repaired}"
echo "  dry_run=${dry_run_count}"
echo "  missing=${missing}"
echo "  failed=${failed}"

if (( failed > 0 )); then
  exit 2
fi

#!/usr/bin/env python3

"""Internal utility for combining Sourccey datasets."""

import argparse
import csv
import datetime as dt
import json
import random
import shlex
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from lerobot.datasets.feature_utils import features_equal_for_merge

# -----------------------------------------------------------------------------
# Editable default merge configuration
# -----------------------------------------------------------------------------
# Every dataset listed here is included in full.
DEFAULT_PARENTS = [
    "/home/sourccey/.cache/huggingface/lerobot/Combination/sourccey-shirt-fold-c-009",
    "/home/sourccey/.cache/huggingface/lerobot/Combination/sourccey-shirt-fold-c-specific-000"
    
]

# Each entry takes a random subset from one dataset. Add more entries to sample
# multiple datasets, or edit episode_count to change the sample size.
DEFAULT_SAMPLES = [
    # {
    #     # "dataset_root": "/home/sourccey/.cache/huggingface/lerobot/Combination/sourccey-shirt-fold-c-009",
    #     # "episode_count": 215,
    # },
]

DEFAULT_SAMPLE_SEED = 42
DEFAULT_DATASET_REPO = "Combination/sourccey-shirt-fold-c-010"

HF_LEROBOT_HOME = Path("/home/sourccey/.cache/huggingface/lerobot")


@dataclass(frozen=True)
class DatasetCandidate:
    root: Path
    repo_id: str
    features: dict
    total_episodes: int
    selected_episode_indices: tuple[int, ...] | None = None
    video_span_repair_episode_indices: tuple[int, ...] = ()
    merge_root: Path | None = None
    merge_repo_id: str | None = None

    @property
    def effective_root(self) -> Path:
        return self.merge_root or self.root

    @property
    def effective_repo_id(self) -> str:
        return self.merge_repo_id or self.repo_id


def is_dataset_root(path: Path) -> bool:
    return (
        (path / "meta" / "info.json").is_file()
        and (path / "meta" / "tasks.parquet").is_file()
        and (path / "data").is_dir()
    )


def discover_dataset_roots(parents: list[Path]) -> list[Path]:
    roots: list[Path] = []

    for parent in parents:
        if not parent.exists():
            raise SystemExit(f"Missing parent folder: {parent}")

        if is_dataset_root(parent):
            roots.append(parent.resolve())
            continue

        for child in sorted(parent.iterdir()):
            if child.is_dir() and is_dataset_root(child):
                roots.append(child.resolve())

    return sorted(dict.fromkeys(roots))


def load_dataset_info(path: Path) -> tuple[dict, int, float]:
    info_path = path / "meta" / "info.json"
    try:
        info = json.loads(info_path.read_text())
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing info.json for dataset root: {path}") from exc

    features = info.get("features")
    if not isinstance(features, dict):
        raise SystemExit(f"Invalid features metadata in {info_path}")

    total_episodes = info.get("total_episodes")
    if not isinstance(total_episodes, int) or total_episodes < 0:
        raise SystemExit(
            f"Invalid total_episodes in {info_path}: expected non-negative int, got {total_episodes!r}"
        )

    fps = info.get("fps")
    if not isinstance(fps, int | float) or isinstance(fps, bool) or fps <= 0:
        raise SystemExit(f"Invalid fps in {info_path}: expected positive number, got {fps!r}")

    return features, total_episodes, float(fps)


def find_split_compatible_episode_indices(
    root: Path, features: dict, total_episodes: int, fps: float
) -> tuple[list[int], list[int], list[int]]:
    """Classify exact, safely trimmable, and unrepairable episode video spans."""
    video_keys = [key for key, feature in features.items() if feature.get("dtype") == "video"]
    if not video_keys:
        return list(range(total_episodes)), [], []

    columns = ["episode_index", "length"]
    for video_key in video_keys:
        columns.extend(
            [
                f"videos/{video_key}/from_timestamp",
                f"videos/{video_key}/to_timestamp",
            ]
        )

    episode_paths = sorted((root / "meta" / "episodes").rglob("*.parquet"))
    if not episode_paths:
        raise SystemExit(f"Missing episode metadata parquet files for sampled dataset: {root}")

    rows_by_index: dict[int, dict] = {}
    for episode_path in episode_paths:
        try:
            rows = pq.read_table(episode_path, columns=columns).to_pylist()
        except (KeyError, OSError) as exc:
            raise SystemExit(f"Cannot validate video spans in {episode_path}: {exc}") from exc
        for row in rows:
            episode_index = row["episode_index"]
            if not isinstance(episode_index, int) or episode_index in rows_by_index:
                raise SystemExit(f"Invalid or duplicate episode_index {episode_index!r} in {episode_path}")
            rows_by_index[episode_index] = row

    expected_indices = set(range(total_episodes))
    actual_indices = set(rows_by_index)
    if actual_indices != expected_indices:
        missing = sorted(expected_indices - actual_indices)
        unexpected = sorted(actual_indices - expected_indices)
        raise SystemExit(
            f"Episode metadata indices do not match total_episodes for {root}; "
            f"missing={missing[:10]}, unexpected={unexpected[:10]}"
        )

    compatible: list[int] = []
    repairable: list[int] = []
    unrepairable: list[int] = []
    for episode_index in range(total_episodes):
        row = rows_by_index[episode_index]
        episode_length = row["length"]
        spans_match = isinstance(episode_length, int)
        spans_can_be_trimmed = spans_match
        for video_key in video_keys:
            from_timestamp = row[f"videos/{video_key}/from_timestamp"]
            to_timestamp = row[f"videos/{video_key}/to_timestamp"]
            if not isinstance(from_timestamp, int | float) or not isinstance(to_timestamp, int | float):
                spans_match = False
                spans_can_be_trimmed = False
                break
            from_frame = round(from_timestamp * fps)
            to_frame = round(to_timestamp * fps)
            video_span_length = to_frame - from_frame
            if episode_length != video_span_length:
                spans_match = False
            if not isinstance(episode_length, int) or video_span_length < episode_length:
                spans_can_be_trimmed = False

        if spans_match:
            compatible.append(episode_index)
        elif spans_can_be_trimmed:
            repairable.append(episode_index)
        else:
            unrepairable.append(episode_index)

    return compatible, repairable, unrepairable


def feature_signature(features: dict) -> str:
    return json.dumps(features, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_candidates(roots: list[Path]) -> list[DatasetCandidate]:
    candidates: list[DatasetCandidate] = []
    for root in roots:
        features, total_episodes, _ = load_dataset_info(root)
        candidates.append(
            DatasetCandidate(
                root=root,
                repo_id=root.name,
                features=features,
                total_episodes=total_episodes,
            )
        )
    return candidates


def build_sample_candidates(
    samples: list[list[str] | dict[str, str | int]], seed: int
) -> list[DatasetCandidate]:
    """Build candidates containing reproducibly sampled episode indices."""
    rng = random.Random(seed)
    candidates: list[DatasetCandidate] = []
    seen_roots: set[Path] = set()

    for sample in samples:
        if isinstance(sample, dict):
            try:
                root_raw = sample["dataset_root"]
                episode_count_raw = sample["episode_count"]
            except KeyError as exc:
                raise SystemExit(
                    f"Invalid DEFAULT_SAMPLES entry {sample!r}; expected dataset_root and episode_count"
                ) from exc
        else:
            root_raw, episode_count_raw = sample

        root = Path(root_raw).expanduser().resolve()
        if root in seen_roots:
            raise SystemExit(f"Sample dataset was provided more than once: {root}")
        if not is_dataset_root(root):
            raise SystemExit(f"Sample path is not a LeRobot dataset root: {root}")

        try:
            episode_count = int(episode_count_raw)
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Invalid sample episode count for {root}: {episode_count_raw!r}") from exc

        features, source_total_episodes, fps = load_dataset_info(root)
        if episode_count < 1:
            raise SystemExit(f"Sample episode count must be at least 1 for {root}")
        compatible_indices, repairable_indices, unrepairable_indices = (
            find_split_compatible_episode_indices(root, features, source_total_episodes, fps)
        )
        sample_pool = sorted(compatible_indices + repairable_indices)
        if unrepairable_indices:
            preview = ", ".join(str(index) for index in unrepairable_indices[:20])
            if len(unrepairable_indices) > 20:
                preview += ", ..."
            print(
                f"Excluded {len(unrepairable_indices)} episodes whose video spans are shorter than "
                f"their data and cannot be repaired by trimming in {root}: {preview}"
            )
        if episode_count > source_total_episodes:
            raise SystemExit(
                f"Cannot sample {episode_count} episodes from {root}; "
                f"it only contains {source_total_episodes}"
            )
        if episode_count > len(sample_pool):
            raise SystemExit(
                f"Cannot sample {episode_count} episodes from {root}; only {len(sample_pool)} of "
                f"{source_total_episodes} are split-compatible or safely trimmable"
            )

        # Sorting preserves the source dataset's chronological order in the materialized subset.
        selected_episode_indices = tuple(sorted(rng.sample(sample_pool, episode_count)))
        repairable_set = set(repairable_indices)
        repair_episode_indices = tuple(
            index for index in selected_episode_indices if index in repairable_set
        )
        if repairable_indices:
            preview = ", ".join(str(index) for index in repairable_indices[:20])
            if len(repairable_indices) > 20:
                preview += ", ..."
            print(
                f"Detected {len(repairable_indices)} episodes with excess trailing video frames "
                f"in {root}: {preview}"
            )
        if repair_episode_indices:
            print(
                f"The random sample selected {len(repair_episode_indices)} of them; their temporary "
                "subset clips will be trimmed to episode.length frames."
            )

        candidates.append(
            DatasetCandidate(
                root=root,
                repo_id=root.name,
                features=features,
                total_episodes=episode_count,
                selected_episode_indices=selected_episode_indices,
                video_span_repair_episode_indices=repair_episode_indices,
            )
        )
        seen_roots.add(root)

    return candidates


def filter_candidates_by_feature(
    candidates: list[DatasetCandidate], require_features: list[str], exclude_features: list[str]
) -> tuple[list[DatasetCandidate], list[DatasetCandidate]]:
    if not require_features and not exclude_features:
        return candidates, []

    kept: list[DatasetCandidate] = []
    dropped: list[DatasetCandidate] = []
    require_set = set(require_features)
    exclude_set = set(exclude_features)

    for candidate in candidates:
        feature_keys = set(candidate.features.keys())
        if require_set and not require_set.issubset(feature_keys):
            dropped.append(candidate)
            continue
        if exclude_set and (exclude_set & feature_keys):
            dropped.append(candidate)
            continue
        kept.append(candidate)

    return kept, dropped


def group_candidates_by_schema(
    candidates: list[DatasetCandidate],
) -> tuple[dict[str, list[DatasetCandidate]], dict[str, dict]]:
    grouped: dict[str, list[DatasetCandidate]] = defaultdict(list)
    features_by_sig: dict[str, dict] = {}

    for candidate in candidates:
        sig = next(
            (
                existing_sig
                for existing_sig, features in features_by_sig.items()
                if features_equal_for_merge(features, candidate.features)
            ),
            None,
        )
        if sig is None:
            sig = feature_signature(candidate.features)
            features_by_sig[sig] = candidate.features
        grouped[sig].append(candidate)

    for sig in grouped:
        grouped[sig].sort(key=lambda c: str(c.root))

    return dict(grouped), features_by_sig


def schema_label(idx: int) -> str:
    return f"schema_{idx:02d}"


def print_root_preview(candidates: list[DatasetCandidate], verbose: bool) -> None:
    def format_candidate(candidate: DatasetCandidate) -> str:
        if candidate.selected_episode_indices is None:
            return str(candidate.root)
        return f"{candidate.root} (random sample: {candidate.total_episodes} episodes)"

    if verbose:
        for candidate in candidates:
            print(f"  - {format_candidate(candidate)}")
        return

    preview_count = min(10, len(candidates))
    print("Preview:")
    for candidate in candidates[:preview_count]:
        print(f"  - {format_candidate(candidate)}")
    if len(candidates) > preview_count:
        print(f"  ... ({len(candidates) - preview_count} more; use --verbose-roots to print all)")


def print_schema_groups(grouped: dict[str, list[DatasetCandidate]], features_by_sig: dict[str, dict]) -> None:
    print("\nDetected multiple feature schemas:")
    for idx, (sig, candidates) in enumerate(
        sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True), start=1
    ):
        features = features_by_sig[sig]
        feature_keys = sorted(features.keys())
        print(f"  [{idx}] {schema_label(idx)}: {len(candidates)} datasets")
        print(f"      features: {', '.join(feature_keys)}")
        print(f"      sample: {candidates[0].root}")


def resolve_group_root(base_out_root: Path | None, repo_id: str) -> Path:
    if base_out_root is None:
        return HF_LEROBOT_HOME / repo_id
    return base_out_root.parent / repo_id


def lineage_csv_path(out_root: Path) -> Path:
    return out_root / "_reports" / "episode_lineage.csv"


def write_episode_lineage_csv(candidates: list[DatasetCandidate], csv_path: Path) -> tuple[Path, int]:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    row_count = 0
    merged_episode_index = 0
    expected_row_count = sum(candidate.total_episodes for candidate in candidates)
    fields = [
        "merged_episode_index",
        "source_dataset_index",
        "source_repo_id",
        "source_root",
        "source_episode_index",
    ]

    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for source_dataset_index, candidate in enumerate(candidates):
            source_episode_indices = candidate.selected_episode_indices or tuple(
                range(candidate.total_episodes)
            )
            for source_episode_index in source_episode_indices:
                writer.writerow(
                    {
                        "merged_episode_index": merged_episode_index,
                        "source_dataset_index": source_dataset_index,
                        "source_repo_id": candidate.repo_id,
                        "source_root": str(candidate.root),
                        "source_episode_index": source_episode_index,
                    }
                )
                merged_episode_index += 1
                row_count += 1

    if row_count != expected_row_count:
        raise SystemExit(
            f"Lineage row count mismatch for {csv_path}: wrote {row_count}, expected {expected_row_count}"
        )

    return csv_path, row_count


def create_repaired_sample_source(candidate: DatasetCandidate, repaired_root: Path) -> Path:
    """Create a temporary source view with selected video spans trimmed to data length."""
    repair_indices = set(candidate.video_span_repair_episode_indices)
    if not repair_indices:
        return candidate.root

    _, _, fps = load_dataset_info(candidate.root)
    video_keys = [
        key for key, feature in candidate.features.items() if feature.get("dtype") == "video"
    ]
    if not video_keys:
        raise SystemExit(f"Cannot repair video spans in dataset without video features: {candidate.root}")

    shutil.copytree(candidate.root / "meta", repaired_root / "meta")
    (repaired_root / "data").symlink_to(candidate.root / "data", target_is_directory=True)
    if (candidate.root / "videos").is_dir():
        (repaired_root / "videos").symlink_to(candidate.root / "videos", target_is_directory=True)

    repaired_indices: set[int] = set()
    for episode_path in sorted((repaired_root / "meta" / "episodes").rglob("*.parquet")):
        table = pq.read_table(episode_path)
        episode_indices = table["episode_index"].to_pylist()
        row_positions = {
            row_position
            for row_position, episode_index in enumerate(episode_indices)
            if episode_index in repair_indices
        }
        if not row_positions:
            continue

        lengths = table["length"].to_pylist()
        for video_key in video_keys:
            from_column_name = f"videos/{video_key}/from_timestamp"
            to_column_name = f"videos/{video_key}/to_timestamp"
            from_timestamps = table[from_column_name].to_pylist()
            to_timestamps = table[to_column_name].to_pylist()
            for row_position in row_positions:
                from_frame = round(from_timestamps[row_position] * fps)
                to_timestamps[row_position] = (from_frame + lengths[row_position]) / fps

            column_index = table.schema.get_field_index(to_column_name)
            table = table.set_column(
                column_index,
                to_column_name,
                pa.array(to_timestamps, type=table.schema.field(column_index).type),
            )

        pq.write_table(table, episode_path)
        repaired_indices.update(episode_indices[row_position] for row_position in row_positions)

    if repaired_indices != repair_indices:
        missing = sorted(repair_indices - repaired_indices)
        raise SystemExit(f"Could not locate selected episodes for temporary video-span repair: {missing}")

    compatible, repairable, unrepairable = find_split_compatible_episode_indices(
        repaired_root, candidate.features, load_dataset_info(candidate.root)[1], fps
    )
    del compatible
    still_incompatible = sorted(repair_indices & (set(repairable) | set(unrepairable)))
    if still_incompatible:
        raise SystemExit(f"Temporary video-span repair failed for episodes: {still_incompatible}")

    return repaired_root


def materialize_random_subsets(
    candidates: list[DatasetCandidate],
    temp_root: Path,
    config_path: Path,
    dry_run: bool,
) -> list[DatasetCandidate]:
    """Create temporary LeRobot datasets containing only selected episodes."""
    prepared: list[DatasetCandidate] = []
    sample_number = 0

    for candidate in candidates:
        if candidate.selected_episode_indices is None:
            prepared.append(candidate)
            continue

        sample_number += 1
        sample_base = temp_root / f"sample_{sample_number:03d}"
        sample_root = sample_base / "selected"
        sample_repo_id = f"{candidate.repo_id}_selected"
        subset_source_root = candidate.root
        repair_indices = candidate.video_span_repair_episode_indices
        if repair_indices:
            repaired_source_root = temp_root / f"sample_{sample_number:03d}_repaired_source"
            repair_preview = ", ".join(str(index) for index in repair_indices)
            print(
                f"\nRepairing {len(repair_indices)} selected episode video spans in a temporary "
                f"source view: {repair_preview}"
            )
            if dry_run:
                subset_source_root = repaired_source_root
                print(f"Dry run enabled; not creating temporary repaired source: {repaired_source_root}")
            else:
                subset_source_root = create_repaired_sample_source(candidate, repaired_source_root)
                print(f"Created temporary repaired source: {subset_source_root}")

        subset_config_path = config_path.with_name(
            f"{config_path.stem}__sample_{sample_number:03d}{config_path.suffix or '.json'}"
        )
        subset_cfg = {
            "repo_id": candidate.repo_id,
            "root": str(subset_source_root),
            "new_root": str(sample_base),
            "operation": {
                "type": "split",
                "splits": {"selected": list(candidate.selected_episode_indices)},
            },
        }
        subset_config_path.parent.mkdir(parents=True, exist_ok=True)
        subset_config_path.write_text(json.dumps(subset_cfg, indent=2))

        indices_preview = ", ".join(str(index) for index in candidate.selected_episode_indices[:10])
        if len(candidate.selected_episode_indices) > 10:
            indices_preview += ", ..."
        print(f"\nRandom subset {sample_number}: {candidate.total_episodes} episodes from {candidate.root}")
        print(f"Selected source episode indices: {indices_preview}")
        print(f"Wrote subset config: {subset_config_path}")

        cmd = ["uv", "run", "lerobot-edit-dataset", "--config_path", str(subset_config_path)]
        print(f"Running: {' '.join(shlex.quote(x) for x in cmd)}")
        if dry_run:
            print("Dry run enabled; not materializing random subset.")
        else:
            subprocess.run(cmd, check=True)

        prepared.append(replace(candidate, merge_root=sample_root, merge_repo_id=sample_repo_id))

    return prepared


def run_merge(
    candidates: list[DatasetCandidate],
    out_repo: str,
    out_root: Path,
    config_path: Path,
    dry_run: bool,
    keep_temp_subsets: bool,
) -> None:
    final_lineage_path = lineage_csv_path(out_root)
    premerge_lineage_path = config_path.with_name(f"{config_path.stem}__episode_lineage.csv")

    if not dry_run and out_root.exists():
        raise SystemExit(
            f"Output root already exists and merge requires a fresh directory: {out_root}\n"
            "If this is from a prior failed run, remove it first and retry."
        )

    has_random_subsets = any(candidate.selected_episode_indices is not None for candidate in candidates)
    created_temp_root = False
    if has_random_subsets and not dry_run:
        out_root.parent.mkdir(parents=True, exist_ok=True)
        temp_root = Path(tempfile.mkdtemp(prefix=f".{out_root.name}__combine_", dir=out_root.parent))
        created_temp_root = True
    else:
        temp_root = out_root.parent / f".{out_root.name}__combine_dry_run"

    try:
        merge_candidates = materialize_random_subsets(
            candidates, temp_root=temp_root, config_path=config_path, dry_run=dry_run
        )
        lineage_path, lineage_rows = write_episode_lineage_csv(candidates, premerge_lineage_path)

        cfg = {
            "new_repo_id": out_repo,
            "new_root": str(out_root),
            "operation": {
                "type": "merge",
                "repo_ids": [candidate.effective_repo_id for candidate in merge_candidates],
                "roots": [str(candidate.effective_root) for candidate in merge_candidates],
            },
        }

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(cfg, indent=2))

        print(f"\nWrote merge config: {config_path}")
        print(f"Output repo_id: {out_repo}")
        print(f"Output root: {out_root}")
        print(f"Wrote episode lineage CSV: {lineage_path} ({lineage_rows} rows)")

        cmd = ["uv", "run", "lerobot-edit-dataset", "--config_path", str(config_path)]
        print(f"\nRunning: {' '.join(shlex.quote(x) for x in cmd)}")

        if dry_run:
            print("Dry run enabled; not executing merge command.")
            return

        subprocess.run(cmd, check=True)

        final_lineage_path.parent.mkdir(parents=True, exist_ok=True)
        lineage_path.replace(final_lineage_path)
        print(f"Moved episode lineage CSV to: {final_lineage_path}")
    finally:
        if created_temp_root:
            if keep_temp_subsets:
                print(f"Kept temporary subset datasets at: {temp_root}")
            else:
                shutil.rmtree(temp_root)
                print(f"Removed temporary subset datasets: {temp_root}")


def default_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Merge full LeRobot datasets, optionally including reproducible random episode samples."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=(
            "Example: --sample /path/to/sample-source 100 --parent /path/to/full-dataset "
            "--sample-seed 42 --out-repo Combination/my-merged-dataset"
        ),
    )
    parser.add_argument(
        "--parent",
        dest="parents",
        action="append",
        default=[],
        help="Full dataset root or parent folder. Replaces DEFAULT_PARENTS when supplied.",
    )
    parser.add_argument(
        "--sample",
        dest="samples",
        action="append",
        nargs=2,
        default=[],
        metavar=("DATASET_ROOT", "EPISODES"),
        help=(
            "Take EPISODES random episodes from DATASET_ROOT. Can be repeated; sampled datasets "
            "replace DEFAULT_SAMPLES when supplied and are added to the full datasets."
        ),
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=DEFAULT_SAMPLE_SEED,
        help="Seed used for reproducible random episode sampling.",
    )
    parser.add_argument(
        "--keep-temp-subsets",
        action="store_true",
        help="Keep materialized subset datasets after the merge for debugging or reuse.",
    )
    parser.add_argument(
        "--out-repo",
        dest="out_repo",
        default=None,
        help="Merged output repo id (e.g. Combination/my-merged-dataset).",
    )
    parser.add_argument(
        "--out-root",
        dest="out_root",
        default=None,
        help="Merged output dataset root path. Defaults to $HF_LEROBOT_HOME/<out-repo>.",
    )
    parser.add_argument(
        "--config-path",
        dest="config_path",
        default=None,
        help="Path to write merge config json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build config and print details without running lerobot-edit-dataset.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list discovered dataset roots and exit.",
    )
    parser.add_argument(
        "--verbose-roots",
        action="store_true",
        help="Print every discovered dataset root.",
    )
    parser.add_argument(
        "--require-feature",
        action="append",
        default=[],
        help="Keep only datasets that contain this feature. Can be repeated.",
    )
    parser.add_argument(
        "--exclude-feature",
        action="append",
        default=[],
        help="Drop datasets that contain this feature. Can be repeated.",
    )
    parser.add_argument(
        "--split-by-features",
        action="store_true",
        help="If mixed schemas are found, create one merged output per schema instead of failing.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    parents_raw = args.parents if args.parents else DEFAULT_PARENTS
    parents = [Path(p).expanduser() for p in parents_raw]

    stamp = default_stamp()
    out_repo = args.out_repo or DEFAULT_DATASET_REPO
    base_out_root = Path(args.out_root).expanduser() if args.out_root else None
    out_root = base_out_root if base_out_root else (HF_LEROBOT_HOME / out_repo)
    config_path = (
        Path(args.config_path).expanduser()
        if args.config_path
        else Path(f"/tmp/sourccey_merge_blue_ac_{stamp}.json")
    )

    roots = discover_dataset_roots(parents)
    full_candidates = build_candidates(roots)
    samples_raw = args.samples if args.samples else DEFAULT_SAMPLES
    sample_candidates = build_sample_candidates(samples_raw, seed=args.sample_seed)

    full_roots = {candidate.root for candidate in full_candidates}
    duplicated_roots = full_roots & {candidate.root for candidate in sample_candidates}
    if duplicated_roots:
        duplicated = "\n".join(f"  - {root}" for root in sorted(duplicated_roots))
        raise SystemExit(f"A dataset cannot be included both in full and as a random sample:\n{duplicated}")

    # Put sampled sources first so their lineage is easy to locate in the merged dataset.
    candidates = sample_candidates + full_candidates

    effective_exclusions = sorted(set(args.exclude_feature))
    candidates, dropped = filter_candidates_by_feature(candidates, args.require_feature, effective_exclusions)

    if dropped:
        print(f"Dropped {len(dropped)} roots due to feature filters")

    if len(candidates) < 2:
        raise SystemExit(f"Need at least 2 dataset roots to merge, found {len(candidates)}")

    print(f"Found {len(candidates)} dataset roots")
    print_root_preview(candidates, verbose=args.verbose_roots or args.list_only)

    grouped, features_by_sig = group_candidates_by_schema(candidates)
    if args.list_only:
        if len(grouped) > 1:
            print_schema_groups(grouped, features_by_sig)
        return 0

    if len(grouped) > 1:
        print_schema_groups(grouped, features_by_sig)
        if not args.split_by_features:
            raise SystemExit(
                "\nMixed feature schemas cannot be merged in one pass.\n"
                "Fix options:\n"
                "  1) Narrow by schema with --require-feature / --exclude-feature\n"
                "  2) Auto-merge each schema separately: --split-by-features\n"
            )

        used_labels: set[str] = set()
        merge_jobs: list[tuple[str, list[DatasetCandidate], Path, Path]] = []
        for idx, (_, schema_candidates) in enumerate(
            sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True), start=1
        ):
            label_base = schema_label(idx)
            label = label_base
            suffix = 2
            while label in used_labels:
                label = f"{label_base}_{suffix}"
                suffix += 1
            used_labels.add(label)

            group_repo = f"{out_repo}__{label}"
            group_root = resolve_group_root(base_out_root, group_repo)
            group_config = config_path.with_name(f"{config_path.stem}__{label}{config_path.suffix}")
            merge_jobs.append((group_repo, schema_candidates, group_root, group_config))

        print("\nPlanned schema-specific merges:")
        for repo, schema_candidates, group_root, _ in merge_jobs:
            print(f"  - {repo}: {len(schema_candidates)} datasets -> {group_root}")

        for repo, schema_candidates, group_root, group_config in merge_jobs:
            run_merge(
                schema_candidates,
                repo,
                group_root,
                group_config,
                dry_run=args.dry_run,
                keep_temp_subsets=args.keep_temp_subsets,
            )

        if args.dry_run:
            print("\nSchema-split dry run completed; no output datasets were created.")
            return 0

        print("\nSchema-split merge completed.")
        print("Use one of these depending on training target:")
        for repo, _, group_root, _ in merge_jobs:
            print(f"  - repo_id={repo} root={group_root}")
        return 0

    run_merge(
        candidates,
        out_repo,
        out_root,
        config_path,
        dry_run=args.dry_run,
        keep_temp_subsets=args.keep_temp_subsets,
    )

    if args.dry_run:
        print("\nDry run completed; no output dataset was created.")
        return 0

    print("\nMerge completed.")
    print(f"Merged dataset written to: {out_root}")
    print("\nNext command:")
    print(
        "uv run lerobot-edit-dataset "
        f"--repo_id '{out_repo}' --root '{out_root}' --operation.type info --operation.show_features true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

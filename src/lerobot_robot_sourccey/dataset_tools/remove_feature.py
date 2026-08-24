#!/usr/bin/env python3

"""Internal utility for removing features from Sourccey datasets."""

import argparse
import datetime as dt
import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PARENTS = [
    "/home/sourccey/.cache/huggingface/lerobot/sourccey-013/rollout__sourccey-013__shirt-fold-blue-c/nickm",
]
DEFAULT_FEATURES = ["intervention"]
HF_LEROBOT_HOME = Path("/home/sourccey/.cache/huggingface/lerobot")


@dataclass(frozen=True)
class DatasetRoot:
    path: Path
    features: dict

    @property
    def name(self) -> str:
        return self.path.name


def default_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def is_dataset_root(path: Path) -> bool:
    return (
        (path / "meta" / "info.json").is_file()
        and (path / "meta" / "tasks.parquet").is_file()
        and (path / "data").is_dir()
    )


def load_features(path: Path) -> dict:
    info_path = path / "meta" / "info.json"
    info = json.loads(info_path.read_text())
    features = info.get("features")
    if not isinstance(features, dict):
        raise SystemExit(f"Invalid features metadata in {info_path}")
    return features


def discover_roots(parents: list[Path]) -> list[DatasetRoot]:
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

    deduped = sorted(dict.fromkeys(roots))
    return [DatasetRoot(path=root, features=load_features(root)) for root in deduped]


def validate_output_name_collisions(to_process: list[tuple[DatasetRoot, list[str]]]) -> None:
    by_name: dict[str, list[Path]] = {}
    for root, _ in to_process:
        by_name.setdefault(root.name, []).append(root.path)

    collisions = {name: paths for name, paths in by_name.items() if len(paths) > 1}
    if collisions:
        print("Found dataset name collisions. Output mapping would be ambiguous:")
        for name, paths in sorted(collisions.items()):
            print(f"  - {name}")
            for p in paths:
                print(f"      source: {p}")
        raise SystemExit(
            "Run this script per parent folder (or narrow with --parent) so each output name is unique."
        )


def run_remove_feature(
    *,
    source: DatasetRoot,
    removable_features: list[str],
    out_root: Path,
    config_path: Path,
    dry_run: bool,
) -> None:
    cfg = {
        "repo_id": source.name,
        "root": str(source.path),
        "new_repo_id": out_root.name,
        "new_root": str(out_root),
        "operation": {
            "type": "remove_feature",
            "feature_names": removable_features,
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(cfg, indent=2))

    cmd = ["uv", "run", "lerobot-edit-dataset", "--config_path", str(config_path)]
    print(f"\n[{source.name}] remove {', '.join(removable_features)}")
    print(f"  source: {source.path}")
    print(f"  output: {out_root}")
    print(f"  config: {config_path}")
    print(f"  cmd: {' '.join(shlex.quote(x) for x in cmd)}")

    if dry_run:
        print("  dry-run: skip execution")
        return

    subprocess.run(cmd, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Batch-remove one or more features from all LeRobot dataset roots found under "
            "parent folder(s)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--in-parent",
        "--parent",
        dest="parents",
        action="append",
        default=[],
        help="Input parent folder containing dataset roots. Can be repeated.",
    )
    parser.add_argument(
        "--feature",
        dest="features",
        action="append",
        default=[],
        help="Feature to remove. Can be repeated.",
    )
    parser.add_argument(
        "--out-parent",
        dest="out_parent",
        default=None,
        help=(
            "Output parent folder. Each processed dataset is written exactly as "
            "<out-parent>/<dataset-name>."
        ),
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list discovered dataset roots and whether they need processing.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on how many datasets to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned operations without running lerobot-edit-dataset.",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help="Optional JSON path for a run report (defaults under <out-parent>/_reports/).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    parents_raw = args.parents if args.parents else DEFAULT_PARENTS
    parents = [Path(p).expanduser() for p in parents_raw]
    features = sorted(set(args.features or DEFAULT_FEATURES))
    stamp = default_stamp()

    default_out_parent = HF_LEROBOT_HOME / "Prepared" / f"strip_{'_'.join(features)}_{stamp}"
    out_parent = Path(args.out_parent).expanduser() if args.out_parent else default_out_parent
    out_parent = out_parent.resolve()
    report_path = (
        Path(args.report_path).expanduser().resolve()
        if args.report_path
        else (out_parent / "_reports" / f"remove_feature_report_{stamp}.json")
    )

    roots = discover_roots(parents)
    if len(roots) == 0:
        raise SystemExit("No dataset roots found.")

    print(f"Found {len(roots)} dataset roots")
    print(f"Features to remove: {', '.join(features)}")
    print(f"Input parent(s): {', '.join(str(p) for p in parents)}")
    print(f"Output parent: {out_parent}")

    needs_processing: list[tuple[DatasetRoot, list[str]]] = []
    for root in roots:
        removable = sorted(set(features) & set(root.features.keys()))
        needs_processing.append((root, removable))

    for root, removable in needs_processing[:20]:
        tag = "remove" if removable else "skip"
        print(f"  [{tag}] {root.path}")
    if len(needs_processing) > 20:
        print(f"  ... ({len(needs_processing) - 20} more)")

    to_process = [(root, removable) for root, removable in needs_processing if removable]
    if args.limit is not None:
        to_process = to_process[: max(0, args.limit)]

    print(f"\nDatasets requiring removal: {len(to_process)}")
    if args.list_only:
        return 0

    if len(to_process) == 0:
        print("Nothing to do.")
        return 0

    out_parent.mkdir(parents=True, exist_ok=True)
    config_dir = out_parent / "_configs"
    validate_output_name_collisions(to_process)

    succeeded = 0
    failed = 0
    skipped_existing = 0
    blocked_existing_non_dataset = 0
    failed_items: list[dict] = []
    skipped_items: list[dict] = []
    blocked_items: list[dict] = []

    for idx, (root, removable) in enumerate(to_process, start=1):
        out_root = (out_parent / root.name).resolve()
        cfg_path = config_dir / f"{idx:04d}_{root.name}.json"
        if out_root.exists():
            if is_dataset_root(out_root):
                skipped_existing += 1
                skipped_items.append(
                    {
                        "dataset_name": root.name,
                        "source": str(root.path),
                        "output": str(out_root),
                        "reason": "output_already_exists_as_dataset",
                    }
                )
                continue

            blocked_existing_non_dataset += 1
            blocked_items.append(
                {
                    "dataset_name": root.name,
                    "source": str(root.path),
                    "output": str(out_root),
                    "reason": "output_exists_but_is_not_dataset_root",
                }
            )
            print(f"\n[{root.name}] blocked")
            print(f"  source: {root.path}")
            print(f"  output exists but is not a dataset root: {out_root}")
            print("  fix: remove or rename that output folder, then rerun")
            continue

        try:
            run_remove_feature(
                source=root,
                removable_features=removable,
                out_root=out_root,
                config_path=cfg_path,
                dry_run=args.dry_run,
            )
            succeeded += 1
        except subprocess.CalledProcessError as exc:
            failed += 1
            print(f"  error: remove_feature failed with exit code {exc.returncode}")
            failed_items.append(
                {
                    "dataset_name": root.name,
                    "source": str(root.path),
                    "output": str(out_root),
                    "config": str(cfg_path),
                    "exit_code": exc.returncode,
                }
            )

    report = {
        "timestamp": stamp,
        "features": features,
        "input_parents": [str(p) for p in parents],
        "output_parent": str(out_parent),
        "succeeded": succeeded,
        "failed": failed,
        "skipped_existing": skipped_existing,
        "blocked_existing_non_dataset": blocked_existing_non_dataset,
        "failed_items": failed_items,
        "skipped_items": skipped_items,
        "blocked_items": blocked_items,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))

    print("\nDone.")
    print(f"  succeeded={succeeded}")
    print(f"  failed={failed}")
    print(f"  skipped_existing={skipped_existing}")
    print(f"  blocked_existing_non_dataset={blocked_existing_non_dataset}")
    print(f"  output_parent={out_parent}")
    print(f"  report_path={report_path}")

    if failed_items:
        print("\nFailed datasets:")
        for item in failed_items:
            print(f"  - {item['dataset_name']}")
            print(f"    source: {item['source']}")
            print(f"    output: {item['output']}")
            print(f"    config: {item['config']}")
            print(f"    exit_code: {item['exit_code']}")

    if blocked_items:
        print("\nBlocked outputs (existing non-dataset folders):")
        for item in blocked_items:
            print(f"  - {item['dataset_name']}")
            print(f"    source: {item['source']}")
            print(f"    output: {item['output']}")

    return 2 if (failed or blocked_existing_non_dataset) else 0


if __name__ == "__main__":
    raise SystemExit(main())

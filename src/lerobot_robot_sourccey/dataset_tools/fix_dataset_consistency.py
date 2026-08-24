#!/usr/bin/env python3

"""Internal utility for repairing Sourccey dataset consistency."""

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


def default_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def resolve_dataset_root(dataset_root: str | None, dataset_repo_id: str | None, hf_root: str) -> Path:
    if dataset_root:
        return Path(dataset_root).expanduser().resolve()
    if dataset_repo_id:
        return (Path(hf_root).expanduser().resolve() / dataset_repo_id).resolve()
    raise SystemExit("Provide either --dataset-root or --dataset-repo-id")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=4), encoding="utf-8")


def as_stat_list(x: float) -> list[float]:
    return [float(x)]


def stat_block(arr: np.ndarray) -> dict[str, list[float]]:
    arr = np.asarray(arr)
    return {
        "min": as_stat_list(np.min(arr)),
        "max": as_stat_list(np.max(arr)),
        "mean": as_stat_list(np.mean(arr)),
        "std": as_stat_list(np.std(arr)),
        "count": as_stat_list(arr.shape[0]),
        "q01": as_stat_list(np.percentile(arr, 1)),
        "q10": as_stat_list(np.percentile(arr, 10)),
        "q50": as_stat_list(np.percentile(arr, 50)),
        "q90": as_stat_list(np.percentile(arr, 90)),
        "q99": as_stat_list(np.percentile(arr, 99)),
    }


def backup_file(src: Path, backup_root: Path, dataset_root: Path) -> None:
    rel = src.relative_to(dataset_root)
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)


def atomic_write_table(table: pa.Table, target: Path) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp_fix")
    pq.write_table(table, tmp, compression="snappy")
    tmp.replace(target)


def get_z_index(info: dict[str, Any], key: str) -> int | None:
    ft = info.get("features", {}).get(key)
    if not isinstance(ft, dict):
        return None
    names = ft.get("names")
    if not isinstance(names, list):
        return None
    try:
        return names.index("z.pos")
    except ValueError:
        return None


def fix_z_pos_in_data(
    dataset_root: Path,
    info: dict[str, Any],
    z_target: float,
    z_tol: float,
    dry_run: bool,
    backup_root: Path | None,
    backup_data: bool,
) -> dict[str, Any]:
    data_files = sorted((dataset_root / "data").rglob("*.parquet"))
    if not data_files:
        raise SystemExit(f"No parquet files under {dataset_root / 'data'}")

    action_z_idx = get_z_index(info, "action")
    state_z_idx = get_z_index(info, "observation.state")

    changed_files = 0
    action_changed_rows = 0
    state_changed_rows = 0

    for f in data_files:
        schema_cols = set(pq.read_schema(f).names)
        if "action" not in schema_cols and "observation.state" not in schema_cols:
            continue

        table = pq.read_table(f)
        table_changed = False

        if action_z_idx is not None and "action" in table.column_names:
            col_idx = table.column_names.index("action")
            arr = np.asarray(table["action"].to_pylist(), dtype=np.float32)
            if arr.ndim == 2 and action_z_idx < arr.shape[1]:
                bad = np.abs(arr[:, action_z_idx] - z_target) > z_tol
                n_bad = int(np.count_nonzero(bad))
                n_exact_mismatch = int(np.count_nonzero(arr[:, action_z_idx] != z_target))
                if n_bad > 0:
                    action_changed_rows += n_bad
                if n_exact_mismatch > 0:
                    table_changed = True
                # Always enforce exact z_target value to avoid tiny residual drift.
                arr[:, action_z_idx] = z_target
                new_col = pa.array(arr.tolist(), type=table.schema.field("action").type)
                table = table.set_column(col_idx, "action", new_col)

        if state_z_idx is not None and "observation.state" in table.column_names:
            col_idx = table.column_names.index("observation.state")
            arr = np.asarray(table["observation.state"].to_pylist(), dtype=np.float32)
            if arr.ndim == 2 and state_z_idx < arr.shape[1]:
                bad = np.abs(arr[:, state_z_idx] - z_target) > z_tol
                n_bad = int(np.count_nonzero(bad))
                n_exact_mismatch = int(np.count_nonzero(arr[:, state_z_idx] != z_target))
                if n_bad > 0:
                    state_changed_rows += n_bad
                if n_exact_mismatch > 0:
                    table_changed = True
                # Always enforce exact z_target value to avoid tiny residual drift.
                arr[:, state_z_idx] = z_target
                new_col = pa.array(arr.tolist(), type=table.schema.field("observation.state").type)
                table = table.set_column(col_idx, "observation.state", new_col)

        if table_changed:
            changed_files += 1
            if not dry_run:
                if backup_data and backup_root is not None:
                    backup_file(f, backup_root, dataset_root)
                atomic_write_table(table, f)

    return {
        "data_files_total": len(data_files),
        "data_files_changed": changed_files,
        "action_z_rows_changed": action_changed_rows,
        "state_z_rows_changed": state_changed_rows,
        "action_z_index": action_z_idx,
        "state_z_index": state_z_idx,
    }


def _patch_vector_stat_column(
    table: pa.Table, col_name: str, z_idx: int, target_value: float
) -> tuple[pa.Table, int]:
    if col_name not in table.column_names:
        return table, 0
    col_idx = table.column_names.index(col_name)
    arr = np.asarray(table[col_name].to_pylist(), dtype=np.float64)
    if arr.ndim != 2 or z_idx >= arr.shape[1]:
        return table, 0
    replaced = int(np.count_nonzero(arr[:, z_idx] != target_value))
    arr[:, z_idx] = target_value
    new_col = pa.array(arr.tolist(), type=table.schema.field(col_name).type)
    table = table.set_column(col_idx, col_name, new_col)
    return table, replaced


def sync_z_pos_metadata(
    dataset_root: Path,
    info: dict[str, Any],
    z_target: float,
    dry_run: bool,
    backup_root: Path | None,
) -> dict[str, Any]:
    """Sync z.pos-related metadata after data-level fixes.

    Updates:
    - meta/stats.json for action/observation.state z.pos statistics
    - meta/episodes/*.parquet per-episode z.pos statistics columns
    """
    stats_path = dataset_root / "meta" / "stats.json"
    action_z_idx = get_z_index(info, "action")
    state_z_idx = get_z_index(info, "observation.state")

    stats_json_updated = False
    stats_vectors_updated = 0

    if stats_path.exists():
        stats = read_json(stats_path)
        for key, z_idx in (("action", action_z_idx), ("observation.state", state_z_idx)):
            if z_idx is None:
                continue
            block = stats.get(key)
            if not isinstance(block, dict):
                continue
            for metric in ("min", "max", "mean", "q01", "q10", "q50", "q90", "q99"):
                vec = block.get(metric)
                if isinstance(vec, list) and len(vec) > z_idx:
                    if float(vec[z_idx]) != float(z_target):
                        stats_json_updated = True
                    vec[z_idx] = float(z_target)
                    stats_vectors_updated += 1
            std_vec = block.get("std")
            if isinstance(std_vec, list) and len(std_vec) > z_idx:
                if float(std_vec[z_idx]) != 0.0:
                    stats_json_updated = True
                std_vec[z_idx] = 0.0
                stats_vectors_updated += 1

        if stats_json_updated and not dry_run:
            if backup_root is not None:
                backup_file(stats_path, backup_root, dataset_root)
            write_json(stats_path, stats)

    episodes_files = sorted((dataset_root / "meta" / "episodes").rglob("*.parquet"))
    episodes_files_changed = 0
    episodes_values_replaced = 0
    episodes_columns_touched = 0

    metric_targets = {
        "min": float(z_target),
        "max": float(z_target),
        "mean": float(z_target),
        "q01": float(z_target),
        "q10": float(z_target),
        "q50": float(z_target),
        "q90": float(z_target),
        "q99": float(z_target),
        "std": 0.0,
    }

    for f in episodes_files:
        table = pq.read_table(f)
        file_values_replaced = 0
        file_columns_touched = 0

        for key, z_idx in (("action", action_z_idx), ("observation.state", state_z_idx)):
            if z_idx is None:
                continue
            for metric, target_value in metric_targets.items():
                col_name = f"stats/{key}/{metric}"
                new_table, replaced = _patch_vector_stat_column(table, col_name, z_idx, target_value)
                if replaced > 0:
                    file_values_replaced += replaced
                    file_columns_touched += 1
                table = new_table

        if file_values_replaced > 0:
            episodes_files_changed += 1
            episodes_values_replaced += file_values_replaced
            episodes_columns_touched += file_columns_touched
            if not dry_run:
                if backup_root is not None:
                    backup_file(f, backup_root, dataset_root)
                atomic_write_table(table, f)

    return {
        "action_z_index": action_z_idx,
        "state_z_index": state_z_idx,
        "stats_json_updated": stats_json_updated,
        "stats_vectors_updated": stats_vectors_updated,
        "episodes_files_total": len(episodes_files),
        "episodes_files_changed": episodes_files_changed,
        "episodes_columns_touched": episodes_columns_touched,
        "episodes_values_replaced": episodes_values_replaced,
        "target_z_value": float(z_target),
    }


def strip_intervention_episode_stats(
    dataset_root: Path,
    dry_run: bool,
    backup_root: Path | None,
) -> dict[str, Any]:
    episodes_files = sorted((dataset_root / "meta" / "episodes").rglob("*.parquet"))
    changed_files = 0
    removed_columns_total = 0

    for f in episodes_files:
        table = pq.read_table(f)
        cols = table.column_names
        keep = [c for c in cols if not c.startswith("stats/intervention/")]
        removed = len(cols) - len(keep)
        if removed > 0:
            removed_columns_total += removed
            changed_files += 1
            if not dry_run:
                if backup_root is not None:
                    backup_file(f, backup_root, dataset_root)
                table = table.select(keep)
                atomic_write_table(table, f)

    return {
        "episodes_files_total": len(episodes_files),
        "episodes_files_changed": changed_files,
        "removed_intervention_columns_total": removed_columns_total,
    }


def recompute_index_stats_and_cleanup(
    dataset_root: Path,
    dry_run: bool,
    backup_root: Path | None,
) -> dict[str, Any]:
    info_path = dataset_root / "meta" / "info.json"
    stats_path = dataset_root / "meta" / "stats.json"
    data_files = sorted((dataset_root / "data").rglob("*.parquet"))

    info = read_json(info_path)
    stats = read_json(stats_path)

    eps_parts: list[np.ndarray] = []
    frame_parts: list[np.ndarray] = []
    idx_parts: list[np.ndarray] = []
    task_parts: list[np.ndarray] = []

    for f in data_files:
        t = pq.read_table(f, columns=["episode_index", "frame_index", "index", "task_index"])
        eps_parts.append(np.asarray(t["episode_index"].to_numpy(), dtype=np.int64))
        frame_parts.append(np.asarray(t["frame_index"].to_numpy(), dtype=np.int64))
        idx_parts.append(np.asarray(t["index"].to_numpy(), dtype=np.int64))
        task_parts.append(np.asarray(t["task_index"].to_numpy(), dtype=np.int64))

    episode_index = np.concatenate(eps_parts)
    frame_index = np.concatenate(frame_parts)
    index = np.concatenate(idx_parts)
    task_index = np.concatenate(task_parts)

    total_frames = int(index.shape[0])
    total_episodes = int(np.unique(episode_index).shape[0])

    stats["episode_index"] = stat_block(episode_index)
    stats["frame_index"] = stat_block(frame_index)
    stats["index"] = stat_block(index)
    stats["task_index"] = stat_block(task_index)

    if "intervention" in stats:
        del stats["intervention"]

    info_features = info.get("features")
    if isinstance(info_features, dict) and "intervention" in info_features:
        del info_features["intervention"]

    info["total_frames"] = total_frames
    info["total_episodes"] = total_episodes

    if not dry_run:
        if backup_root is not None:
            backup_file(stats_path, backup_root, dataset_root)
            backup_file(info_path, backup_root, dataset_root)
        write_json(stats_path, stats)
        write_json(info_path, info)

    return {
        "total_frames": total_frames,
        "total_episodes": total_episodes,
        "stats_keys_rewritten": ["episode_index", "frame_index", "index", "task_index"],
        "removed_stats_intervention_key": ("intervention" in read_json(stats_path)) if dry_run else False,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Fix dataset consistency issues: enforce z.pos target, remove meta/episodes "
            "intervention stats columns, repair index-related stats metadata, and "
            "sync z.pos metadata fields."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--dataset-root", type=str, default=None)
    p.add_argument("--dataset-repo-id", type=str, default=None)
    p.add_argument("--hf-root", type=str, default=str(Path.home() / ".cache/huggingface/lerobot"))
    p.add_argument("--z-target", type=float, default=100.0)
    p.add_argument("--z-tol", type=float, default=1e-6)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--backup-data",
        action="store_true",
        help="Also backup modified data parquet files (can be large).",
    )
    p.add_argument(
        "--backup-root",
        type=str,
        default=None,
        help="Optional backup root. Defaults to <dataset_root>/_consistency_fix_backups/<timestamp>",
    )
    p.add_argument("--report-path", type=str, default=None)
    return p


def main() -> int:
    args = build_parser().parse_args()
    stamp = default_stamp()

    dataset_root = resolve_dataset_root(args.dataset_root, args.dataset_repo_id, args.hf_root)
    info_path = dataset_root / "meta" / "info.json"
    if not info_path.exists():
        raise SystemExit(f"Not a dataset root (missing {info_path})")

    backup_root = (
        Path(args.backup_root).expanduser().resolve()
        if args.backup_root
        else (dataset_root / "_consistency_fix_backups" / stamp)
    )

    info = read_json(info_path)

    if not args.dry_run:
        backup_root.mkdir(parents=True, exist_ok=True)

    z_result = fix_z_pos_in_data(
        dataset_root=dataset_root,
        info=info,
        z_target=args.z_target,
        z_tol=args.z_tol,
        dry_run=args.dry_run,
        backup_root=backup_root,
        backup_data=args.backup_data,
    )

    epi_result = strip_intervention_episode_stats(
        dataset_root=dataset_root,
        dry_run=args.dry_run,
        backup_root=backup_root,
    )

    stats_result = recompute_index_stats_and_cleanup(
        dataset_root=dataset_root,
        dry_run=args.dry_run,
        backup_root=backup_root,
    )

    z_meta_result = sync_z_pos_metadata(
        dataset_root=dataset_root,
        info=info,
        z_target=args.z_target,
        dry_run=args.dry_run,
        backup_root=backup_root,
    )

    report = {
        "timestamp": dt.datetime.now().isoformat(),
        "dataset_root": str(dataset_root),
        "dry_run": args.dry_run,
        "backup_root": str(backup_root),
        "backup_data": args.backup_data,
        "z_fix": z_result,
        "episodes_meta_fix": epi_result,
        "stats_fix": stats_result,
        "z_metadata_fix": z_meta_result,
    }

    report_path = (
        Path(args.report_path).expanduser().resolve()
        if args.report_path
        else Path("outputs") / f"dataset_consistency_fix_{dataset_root.name}_{stamp}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Dataset root: {dataset_root}")
    print(f"Dry run: {args.dry_run}")
    print(f"Backup root: {backup_root}")
    print(f"Report: {report_path}")
    print("\nChanges summary:")
    print(
        "  z.pos fixes: "
        f"action_rows={z_result['action_z_rows_changed']} "
        f"state_rows={z_result['state_z_rows_changed']} "
        f"files_changed={z_result['data_files_changed']}/{z_result['data_files_total']}"
    )
    print(
        "  meta/episodes intervention column removals: "
        f"removed_cols={epi_result['removed_intervention_columns_total']} "
        f"files_changed={epi_result['episodes_files_changed']}/{epi_result['episodes_files_total']}"
    )
    print(
        "  index stats rewritten for keys: "
        f"{', '.join(stats_result['stats_keys_rewritten'])}; "
        f"total_frames={stats_result['total_frames']} total_episodes={stats_result['total_episodes']}"
    )
    print(
        "  z metadata sync: "
        f"stats_json_updated={z_meta_result['stats_json_updated']} "
        f"episodes_files_changed={z_meta_result['episodes_files_changed']}/{z_meta_result['episodes_files_total']} "
        f"values_replaced={z_meta_result['episodes_values_replaced']} "
        f"target={z_meta_result['target_z_value']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

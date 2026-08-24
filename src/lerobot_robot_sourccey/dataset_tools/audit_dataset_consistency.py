#!/usr/bin/env python3

"""Internal utility for auditing Sourccey dataset consistency."""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq


def default_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def as_scalar(x: Any) -> float:
    if isinstance(x, (list, tuple, np.ndarray)):
        if len(x) == 0:
            return float("nan")
        return float(np.asarray(x).reshape(-1)[0])
    return float(x)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_dataset_root(
    dataset_root: str | None,
    dataset_repo_id: str | None,
    hf_root: str,
) -> Path:
    if dataset_root:
        return Path(dataset_root).expanduser().resolve()
    if dataset_repo_id:
        return (Path(hf_root).expanduser().resolve() / dataset_repo_id).resolve()
    raise SystemExit("Provide either --dataset-root or --dataset-repo-id")


def get_z_index(feature_info: dict | None) -> int | None:
    if not feature_info:
        return None
    names = feature_info.get("names")
    if not isinstance(names, list):
        return None
    try:
        return names.index("z.pos")
    except ValueError:
        return None


def extract_stats_meta_field(stats: dict, key: str, field: str) -> float | None:
    v = stats.get(key, {}).get(field)
    if v is None:
        return None
    return as_scalar(v)


def audit_dataset(
    root: Path,
    z_target: float,
    z_tol: float,
) -> dict:
    info_path = root / "meta" / "info.json"
    stats_path = root / "meta" / "stats.json"
    episodes_dir = root / "meta" / "episodes"
    data_dir = root / "data"

    if not info_path.exists():
        raise SystemExit(f"Missing file: {info_path}")
    if not stats_path.exists():
        raise SystemExit(f"Missing file: {stats_path}")
    if not data_dir.exists():
        raise SystemExit(f"Missing folder: {data_dir}")

    info = read_json(info_path)
    stats = read_json(stats_path)
    features = info.get("features", {})
    if not isinstance(features, dict):
        raise SystemExit(f"Invalid features in {info_path}")

    data_files = sorted(data_dir.rglob("*.parquet"))
    if not data_files:
        raise SystemExit(f"No parquet files found in {data_dir}")

    action_idx = get_z_index(features.get("action"))
    state_idx = get_z_index(features.get("observation.state"))
    has_intervention_feature = "intervention" in features

    # Running aggregates from raw data
    total_rows = 0
    ep_min = None
    ep_max = None
    fr_min = None
    fr_max = None
    idx_min = None
    idx_max = None
    task_min = None
    task_max = None
    unique_episode_ids: set[int] = set()
    intervention_episodes_data: set[int] = set()
    intervention_nonzero_frames = 0
    intervention_column_present = False

    action_z_non_target = 0
    action_z_min = None
    action_z_max = None
    action_z_non_target_eps: set[int] = set()
    action_rows_checked = 0

    state_z_non_target = 0
    state_z_min = None
    state_z_max = None
    state_z_non_target_eps: set[int] = set()
    state_rows_checked = 0

    for f in data_files:
        schema_cols = set(pq.read_schema(f).names)
        wanted_cols = [
            "episode_index",
            "frame_index",
            "index",
            "task_index",
            "action",
            "observation.state",
            "intervention",
        ]
        selected_cols = [c for c in wanted_cols if c in schema_cols]
        table = pq.read_table(f, columns=selected_cols)
        cols = set(table.column_names)

        ep = np.asarray(table["episode_index"].to_numpy(), dtype=np.int64)
        fr = np.asarray(table["frame_index"].to_numpy(), dtype=np.int64)
        ix = np.asarray(table["index"].to_numpy(), dtype=np.int64)
        tk = np.asarray(table["task_index"].to_numpy(), dtype=np.int64)

        total_rows += int(ep.shape[0])
        unique_episode_ids.update(int(x) for x in np.unique(ep))

        ep_min = int(ep.min()) if ep_min is None else min(ep_min, int(ep.min()))
        ep_max = int(ep.max()) if ep_max is None else max(ep_max, int(ep.max()))
        fr_min = int(fr.min()) if fr_min is None else min(fr_min, int(fr.min()))
        fr_max = int(fr.max()) if fr_max is None else max(fr_max, int(fr.max()))
        idx_min = int(ix.min()) if idx_min is None else min(idx_min, int(ix.min()))
        idx_max = int(ix.max()) if idx_max is None else max(idx_max, int(ix.max()))
        task_min = int(tk.min()) if task_min is None else min(task_min, int(tk.min()))
        task_max = int(tk.max()) if task_max is None else max(task_max, int(tk.max()))

        if "intervention" in cols:
            intervention_column_present = True
            iv = np.asarray(table["intervention"].to_numpy())
            nz = iv != 0
            intervention_nonzero_frames += int(np.count_nonzero(nz))
            if np.any(nz):
                intervention_episodes_data.update(int(x) for x in np.unique(ep[nz]))

        if action_idx is not None and "action" in cols:
            a = np.asarray(table["action"].to_pylist(), dtype=np.float32)
            z = a[:, action_idx]
            action_rows_checked += int(z.shape[0])
            zmin = float(np.min(z))
            zmax = float(np.max(z))
            action_z_min = zmin if action_z_min is None else min(action_z_min, zmin)
            action_z_max = zmax if action_z_max is None else max(action_z_max, zmax)
            bad = np.abs(z - z_target) > z_tol
            action_z_non_target += int(np.count_nonzero(bad))
            if np.any(bad):
                action_z_non_target_eps.update(int(x) for x in np.unique(ep[bad]))

        if state_idx is not None and "observation.state" in cols:
            s = np.asarray(table["observation.state"].to_pylist(), dtype=np.float32)
            z = s[:, state_idx]
            state_rows_checked += int(z.shape[0])
            zmin = float(np.min(z))
            zmax = float(np.max(z))
            state_z_min = zmin if state_z_min is None else min(state_z_min, zmin)
            state_z_max = zmax if state_z_max is None else max(state_z_max, zmax)
            bad = np.abs(z - z_target) > z_tol
            state_z_non_target += int(np.count_nonzero(bad))
            if np.any(bad):
                state_z_non_target_eps.update(int(x) for x in np.unique(ep[bad]))

    # Episodes metadata checks
    episode_files = sorted(episodes_dir.rglob("*.parquet")) if episodes_dir.exists() else []
    episodes_intervention_stats_columns: list[str] = []
    episodes_with_intervention_stats_signal: set[int] = set()
    episodes_rows = None
    episodes_sum_length = None
    episodes_ep_min = None
    episodes_ep_max = None

    if episode_files:
        ep_table = pq.read_table(episode_files)
        cols = ep_table.column_names
        episodes_rows = ep_table.num_rows
        if "length" in cols:
            lengths = np.asarray(ep_table["length"].to_numpy(), dtype=np.int64)
            episodes_sum_length = int(lengths.sum())
        if "episode_index" in cols:
            epidx = np.asarray(ep_table["episode_index"].to_numpy(), dtype=np.int64)
            episodes_ep_min = int(epidx.min())
            episodes_ep_max = int(epidx.max())

        episodes_intervention_stats_columns = [c for c in cols if c.startswith("stats/intervention/")]
        max_col = "stats/intervention/max"
        if max_col in cols:
            raw_m = ep_table[max_col].to_pylist()
            vals: list[float] = []
            for v in raw_m:
                if v is None:
                    vals.append(0.0)
                    continue
                try:
                    vals.append(as_scalar(v))
                except Exception:
                    vals.append(0.0)
            m = np.asarray(vals, dtype=np.float32)
            nz = m > 0.0
            if np.any(nz) and "episode_index" in cols:
                epidx = np.asarray(ep_table["episode_index"].to_numpy(), dtype=np.int64)
                episodes_with_intervention_stats_signal.update(int(x) for x in np.unique(epidx[nz]))

    # Stats mismatch checks against raw data
    mismatches: list[str] = []
    if info.get("total_frames") != total_rows:
        mismatches.append(
            f"info.total_frames={info.get('total_frames')} != raw_total_frames={total_rows}"
        )
    if info.get("total_episodes") != len(unique_episode_ids):
        mismatches.append(
            f"info.total_episodes={info.get('total_episodes')} != unique_raw_episode_count={len(unique_episode_ids)}"
        )

    # meta/stats fields
    for k, raw_min, raw_max in [
        ("episode_index", ep_min, ep_max),
        ("frame_index", fr_min, fr_max),
        ("index", idx_min, idx_max),
        ("task_index", task_min, task_max),
    ]:
        s_min = extract_stats_meta_field(stats, k, "min")
        s_max = extract_stats_meta_field(stats, k, "max")
        s_count = extract_stats_meta_field(stats, k, "count")
        if s_min is not None and raw_min is not None and int(round(s_min)) != int(raw_min):
            mismatches.append(f"stats.{k}.min={s_min} != raw_{k}.min={raw_min}")
        if s_max is not None and raw_max is not None and int(round(s_max)) != int(raw_max):
            mismatches.append(f"stats.{k}.max={s_max} != raw_{k}.max={raw_max}")
        if s_count is not None and int(round(s_count)) != int(total_rows):
            mismatches.append(f"stats.{k}.count={s_count} != raw_total_frames={total_rows}")

    if episodes_rows is not None and episodes_rows != len(unique_episode_ids):
        mismatches.append(
            f"meta/episodes rows={episodes_rows} != unique_raw_episode_count={len(unique_episode_ids)}"
        )
    if episodes_sum_length is not None and episodes_sum_length != total_rows:
        mismatches.append(
            f"sum(meta/episodes.length)={episodes_sum_length} != raw_total_frames={total_rows}"
        )
    if episodes_ep_min is not None and ep_min is not None and episodes_ep_min != ep_min:
        mismatches.append(f"meta/episodes.episode_index.min={episodes_ep_min} != raw.min={ep_min}")
    if episodes_ep_max is not None and ep_max is not None and episodes_ep_max != ep_max:
        mismatches.append(f"meta/episodes.episode_index.max={episodes_ep_max} != raw.max={ep_max}")

    report = {
        "dataset_root": str(root),
        "dataset_repo_id": info.get("repo_id"),
        "timestamp": dt.datetime.now().isoformat(),
        "summary": {
            "total_frames_raw": total_rows,
            "total_episodes_raw": len(unique_episode_ids),
            "episode_index_raw_min": ep_min,
            "episode_index_raw_max": ep_max,
            "frame_index_raw_min": fr_min,
            "frame_index_raw_max": fr_max,
            "index_raw_min": idx_min,
            "index_raw_max": idx_max,
            "task_index_raw_min": task_min,
            "task_index_raw_max": task_max,
            "stats_mismatch_count": len(mismatches),
            "intervention_feature_in_info": has_intervention_feature,
            "intervention_column_in_data": intervention_column_present,
            "intervention_nonzero_frames_in_data": intervention_nonzero_frames,
            "intervention_episode_count_in_data": len(intervention_episodes_data),
            "intervention_stats_columns_in_meta_episodes": len(episodes_intervention_stats_columns),
            "intervention_episode_count_from_meta_episode_stats": len(episodes_with_intervention_stats_signal),
        },
        "z_pos_check": {
            "target": z_target,
            "tolerance": z_tol,
            "action": {
                "z_index": action_idx,
                "rows_checked": action_rows_checked,
                "non_target_count": action_z_non_target,
                "non_target_fraction": (action_z_non_target / action_rows_checked) if action_rows_checked else None,
                "z_min": action_z_min,
                "z_max": action_z_max,
                "episode_count_with_non_target": len(action_z_non_target_eps),
                "episodes_with_non_target_sample": sorted(action_z_non_target_eps)[:50],
            },
            "observation.state": {
                "z_index": state_idx,
                "rows_checked": state_rows_checked,
                "non_target_count": state_z_non_target,
                "non_target_fraction": (state_z_non_target / state_rows_checked) if state_rows_checked else None,
                "z_min": state_z_min,
                "z_max": state_z_max,
                "episode_count_with_non_target": len(state_z_non_target_eps),
                "episodes_with_non_target_sample": sorted(state_z_non_target_eps)[:50],
            },
        },
        "stats_mismatches": mismatches,
        "intervention": {
            "episodes_with_intervention_in_data_sample": sorted(intervention_episodes_data)[:100],
            "meta_episode_stats_intervention_columns": episodes_intervention_stats_columns,
            "episodes_with_intervention_signal_in_meta_episode_stats_sample": sorted(
                episodes_with_intervention_stats_signal
            )[:100],
        },
    }
    return report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Audit a LeRobot dataset for stats mismatches, intervention leakage, and z.pos consistency.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--dataset-root", type=str, default=None, help="Path to dataset root.")
    p.add_argument("--dataset-repo-id", type=str, default=None, help="Dataset repo id under --hf-root.")
    p.add_argument(
        "--hf-root",
        type=str,
        default=str(Path.home() / ".cache/huggingface/lerobot"),
        help="HF LeRobot root used with --dataset-repo-id.",
    )
    p.add_argument("--z-target", type=float, default=100.0, help="Expected z.pos value.")
    p.add_argument(
        "--z-tol",
        type=float,
        default=1e-6,
        help="Tolerance for z.pos equality check (abs(z - target) > tol is flagged).",
    )
    p.add_argument("--report-path", type=str, default=None, help="Optional JSON output path.")
    p.add_argument(
        "--fail-on-issues",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Exit non-zero when mismatches/intervention/non-target z.pos are found.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()

    root = resolve_dataset_root(args.dataset_root, args.dataset_repo_id, args.hf_root)
    report = audit_dataset(root=root, z_target=args.z_target, z_tol=args.z_tol)

    slug = root.name.replace("/", "__")
    stamp = default_stamp()
    report_path = (
        Path(args.report_path).expanduser().resolve()
        if args.report_path
        else Path("outputs") / f"dataset_consistency_audit_{slug}_{stamp}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))

    summary = report["summary"]
    z_action = report["z_pos_check"]["action"]
    z_state = report["z_pos_check"]["observation.state"]
    print(f"Dataset root: {root}")
    print(f"Report: {report_path}")
    print(f"Stats mismatches: {summary['stats_mismatch_count']}")
    print(
        "Intervention: "
        f"feature_in_info={summary['intervention_feature_in_info']} "
        f"column_in_data={summary['intervention_column_in_data']} "
        f"nonzero_frames={summary['intervention_nonzero_frames_in_data']} "
        f"meta_episode_stats_cols={summary['intervention_stats_columns_in_meta_episodes']}"
    )
    print(
        "z.pos action: "
        f"non_target={z_action['non_target_count']}/{z_action['rows_checked']} "
        f"frac={z_action['non_target_fraction']}"
    )
    print(
        "z.pos state: "
        f"non_target={z_state['non_target_count']}/{z_state['rows_checked']} "
        f"frac={z_state['non_target_fraction']}"
    )

    has_issues = False
    has_issues |= summary["stats_mismatch_count"] > 0
    has_issues |= bool(summary["intervention_feature_in_info"])
    has_issues |= bool(summary["intervention_column_in_data"])
    has_issues |= int(summary["intervention_nonzero_frames_in_data"]) > 0
    has_issues |= int(summary["intervention_stats_columns_in_meta_episodes"]) > 0
    has_issues |= int(z_action["non_target_count"] or 0) > 0
    has_issues |= int(z_state["non_target_count"] or 0) > 0

    if args.fail_on_issues and has_issues:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

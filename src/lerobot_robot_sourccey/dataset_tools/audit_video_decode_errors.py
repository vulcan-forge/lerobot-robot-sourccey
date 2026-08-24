#!/usr/bin/env python

"""
Scan dataset video files for decode errors and report likely failing frame/time.

This is intended as a preflight integrity check for large LeRobot datasets.
It decodes each MP4 with PyAV and records where decode failures occur.
"""

import argparse
import csv
import json
import logging
import multiprocessing
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import av
from lerobot.datasets.io_utils import load_episodes
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
from lerobot.utils.constants import HF_LEROBOT_HOME
from lerobot.utils.utils import init_logging

_VIDEO_PATH_RE = re.compile(r"^videos/(?P<video_key>[^/]+)/chunk-(?P<chunk>\d+)/file-(?P<file>\d+)\.mp4$")


def _scalar(val) -> float | int:
    if hasattr(val, "item"):
        return val.item()
    return val


def _parse_video_identity(video_rel_path: str) -> tuple[str | None, int | None, int | None]:
    m = _VIDEO_PATH_RE.match(video_rel_path)
    if not m:
        return None, None, None
    return m.group("video_key"), int(m.group("chunk")), int(m.group("file"))


def _resolve_episode_indices(
    total_episodes: int,
    episode_start: int | None,
    episode_end: int | None,
) -> list[int]:
    start = 0 if episode_start is None else max(0, episode_start)
    end = (total_episodes - 1) if episode_end is None else min(total_episodes - 1, episode_end)
    if total_episodes <= 0:
        return []
    if start > end:
        return []
    return list(range(start, end + 1))


def _build_episode_mapping(
    meta: LeRobotDatasetMetadata,
    episodes: Any,
    episode_indices: list[int] | None = None,
) -> dict[tuple[str, int, int], list[int]]:
    mapping: dict[tuple[str, int, int], list[int]] = {}
    idxs = episode_indices if episode_indices is not None else list(range(len(episodes)))
    for ep_idx in idxs:
        ep = episodes[ep_idx]
        for video_key in meta.video_keys:
            try:
                chunk_idx = int(_scalar(ep[f"videos/{video_key}/chunk_index"]))
                file_idx = int(_scalar(ep[f"videos/{video_key}/file_index"]))
            except (KeyError, TypeError, ValueError):
                continue
            key = (video_key, chunk_idx, file_idx)
            mapping.setdefault(key, []).append(ep_idx)

    for key in mapping:
        mapping[key].sort()
    return mapping


def _scan_one_video_file(
    video_path_str: str,
    dataset_root_str: str,
    max_errors_per_file: int,
) -> list[dict[str, Any]]:
    video_path = Path(video_path_str)
    dataset_root = Path(dataset_root_str)
    rel_path = video_path.relative_to(dataset_root).as_posix()

    results: list[dict[str, Any]] = []
    decoded_frames = 0
    packet_index = -1

    try:
        container = av.open(str(video_path))
    except Exception as e:
        return [
            {
                "video_rel_path": rel_path,
                "error_type": type(e).__name__,
                "message": str(e),
                "packet_index": None,
                "packet_pts": None,
                "packet_dts": None,
                "packet_time_s": None,
                "estimated_frame_index": None,
                "decoded_frames_before_error": 0,
                "fps": None,
                "duration_s": None,
            }
        ]

    try:
        if not container.streams.video:
            return [
                {
                    "video_rel_path": rel_path,
                    "error_type": "NoVideoStream",
                    "message": "No video stream found in file.",
                    "packet_index": None,
                    "packet_pts": None,
                    "packet_dts": None,
                    "packet_time_s": None,
                    "estimated_frame_index": None,
                    "decoded_frames_before_error": 0,
                    "fps": None,
                    "duration_s": None,
                }
            ]

        stream = container.streams.video[0]
        fps = float(stream.average_rate) if stream.average_rate is not None else None
        duration_s = None
        if stream.duration is not None and stream.time_base is not None:
            duration_s = float(stream.duration * stream.time_base)
        elif container.duration is not None:
            duration_s = float(container.duration) / 1_000_000.0

        for packet_index, packet in enumerate(container.demux(stream)):
            try:
                for _ in packet.decode():
                    decoded_frames += 1
            except Exception as e:
                packet_time_s = None
                if packet.pts is not None and stream.time_base is not None:
                    packet_time_s = float(packet.pts * stream.time_base)
                elif packet.dts is not None and stream.time_base is not None:
                    packet_time_s = float(packet.dts * stream.time_base)

                est_frame = int(round(packet_time_s * fps)) if (packet_time_s is not None and fps) else None
                results.append(
                    {
                        "video_rel_path": rel_path,
                        "error_type": type(e).__name__,
                        "message": str(e),
                        "packet_index": packet_index,
                        "packet_pts": int(packet.pts) if packet.pts is not None else None,
                        "packet_dts": int(packet.dts) if packet.dts is not None else None,
                        "packet_time_s": packet_time_s,
                        "estimated_frame_index": est_frame,
                        "decoded_frames_before_error": decoded_frames,
                        "fps": fps,
                        "duration_s": duration_s,
                    }
                )
                if len(results) >= max(1, max_errors_per_file):
                    break

        return results
    finally:
        container.close()


def _write_csv(rows: list[dict[str, Any]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "video_rel_path",
        "video_key",
        "chunk_index",
        "file_index",
        "episode_count",
        "episode_indices_preview",
        "error_type",
        "message",
        "packet_index",
        "packet_pts",
        "packet_dts",
        "packet_time_s",
        "estimated_frame_index",
        "decoded_frames_before_error",
        "fps",
        "duration_s",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["episode_indices_preview"] = json.dumps(out.get("episode_indices_preview", []))
            writer.writerow(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit all dataset videos for decode errors and report likely failing frame/time.",
    )
    parser.add_argument("--dataset-repo-id", type=str, required=True, help="Dataset repo ID.")
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help=f"Optional HF root (default: {HF_LEROBOT_HOME}).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(8, (multiprocessing.cpu_count() or 4))),
        help="Number of worker processes.",
    )
    parser.add_argument(
        "--max-errors-per-file",
        type=int,
        default=1,
        help="How many decode errors to record per file before moving on.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap for quick tests.",
    )
    parser.add_argument(
        "--file-start",
        type=int,
        default=0,
        help="0-indexed start offset into sorted candidate video files (applied before --max-files).",
    )
    parser.add_argument(
        "--path-contains",
        type=str,
        default=None,
        help="Optional substring filter on absolute video path (for targeted checks).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="outputs/video_audit",
        help="Directory for audit artifacts.",
    )
    parser.add_argument(
        "--fail-on-issues",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Exit non-zero when any decode issues are found.",
    )
    parser.add_argument(
        "--episode-preview-limit",
        type=int,
        default=20,
        help="Number of episode indices to include per bad file in outputs.",
    )
    parser.add_argument(
        "--episode-start",
        type=int,
        default=None,
        help="Optional start episode index (inclusive, 0-indexed).",
    )
    parser.add_argument(
        "--episode-end",
        type=int,
        default=None,
        help="Optional end episode index (inclusive, 0-indexed).",
    )
    args = parser.parse_args()

    init_logging()

    root = Path(args.root) if args.root else HF_LEROBOT_HOME
    dataset_root = root / args.dataset_repo_id
    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")

    meta = LeRobotDatasetMetadata(repo_id=args.dataset_repo_id, root=dataset_root)
    root_for_episodes = Path(meta.root)
    episodes = meta.episodes
    if episodes is None:
        episodes = load_episodes(root_for_episodes)

    episode_mapping = _build_episode_mapping(meta, episodes)
    selected_episode_indices = _resolve_episode_indices(
        total_episodes=len(episodes),
        episode_start=args.episode_start,
        episode_end=args.episode_end,
    )

    videos_root = dataset_root / "videos"
    video_files = sorted(videos_root.rglob("*.mp4"))
    if args.episode_start is not None or args.episode_end is not None:
        selected_mapping = _build_episode_mapping(meta, episodes, selected_episode_indices)
        selected_identities = set(selected_mapping.keys())
        video_files = [
            p
            for p in video_files
            if _parse_video_identity(p.relative_to(dataset_root).as_posix()) in selected_identities
        ]
    if args.path_contains:
        video_files = [p for p in video_files if args.path_contains in str(p)]
    file_start = max(0, args.file_start)
    if file_start:
        video_files = video_files[file_start:]
    if args.max_files is not None:
        video_files = video_files[: max(0, args.max_files)]

    if not video_files:
        raise FileNotFoundError(
            "No .mp4 files matched the current filters/slice "
            f"(videos_root={videos_root}, path_contains={args.path_contains}, "
            f"file_start={file_start}, max_files={args.max_files})."
        )

    logging.info(
        "Scanning %d video files in %s with %d workers",
        len(video_files),
        videos_root,
        args.workers,
    )
    if args.episode_start is not None or args.episode_end is not None:
        logging.info(
            "Episode filter enabled: [%d, %d] inclusive (0-indexed), %d episode(s)",
            selected_episode_indices[0] if selected_episode_indices else -1,
            selected_episode_indices[-1] if selected_episode_indices else -1,
            len(selected_episode_indices),
        )

    issues: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = {
            ex.submit(
                _scan_one_video_file,
                str(path),
                str(dataset_root),
                args.max_errors_per_file,
            ): path
            for path in video_files
        }
        for i, fut in enumerate(as_completed(futures), start=1):
            if i % 100 == 0 or i == len(futures):
                logging.info("Progress: %d/%d files checked", i, len(futures))
            src_path = futures[fut]
            try:
                rows = fut.result()
            except Exception as e:
                logging.exception("Worker failed while scanning %s: %s", src_path, e)
                issues.append(
                    {
                        "video_rel_path": src_path.relative_to(dataset_root).as_posix(),
                        "video_key": None,
                        "chunk_index": None,
                        "file_index": None,
                        "episode_count": 0,
                        "episode_indices_preview": [],
                        "error_type": type(e).__name__,
                        "message": str(e),
                        "packet_index": None,
                        "packet_pts": None,
                        "packet_dts": None,
                        "packet_time_s": None,
                        "estimated_frame_index": None,
                        "decoded_frames_before_error": 0,
                        "fps": None,
                        "duration_s": None,
                    }
                )
                continue
            if not rows:
                continue
            for row in rows:
                video_key, chunk_idx, file_idx = _parse_video_identity(row["video_rel_path"])
                ep_indices = (
                    episode_mapping.get((video_key, chunk_idx, file_idx), [])
                    if video_key is not None and chunk_idx is not None and file_idx is not None
                    else []
                )
                row["video_key"] = video_key
                row["chunk_index"] = chunk_idx
                row["file_index"] = file_idx
                row["episode_count"] = len(ep_indices)
                row["episode_indices_preview"] = ep_indices[: max(0, args.episode_preview_limit)]
                issues.append(row)

    bad_files = sorted({row["video_rel_path"] for row in issues})
    error_type_counts = dict(Counter(row["error_type"] for row in issues))

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    repo_slug = args.dataset_repo_id.replace("/", "__")

    issues_json = output_dir / f"{repo_slug}_decode_issues.json"
    issues_csv = output_dir / f"{repo_slug}_decode_issues.csv"
    bad_files_txt = output_dir / f"{repo_slug}_bad_files.txt"
    summary_json = output_dir / f"{repo_slug}_decode_summary.json"

    issues_json.write_text(json.dumps(issues, indent=2), encoding="utf-8")
    _write_csv(issues, issues_csv)
    bad_files_txt.write_text("\n".join(bad_files) + ("\n" if bad_files else ""), encoding="utf-8")

    summary = {
        "dataset_repo_id": args.dataset_repo_id,
        "dataset_root": str(dataset_root),
        "file_start": file_start,
        "episode_start": args.episode_start,
        "episode_end": args.episode_end,
        "selected_episode_count": len(selected_episode_indices),
        "files_scanned": len(video_files),
        "files_with_issues": len(bad_files),
        "total_issues": len(issues),
        "error_type_counts": error_type_counts,
        "issues_json": str(issues_json),
        "issues_csv": str(issues_csv),
        "bad_files_txt": str(bad_files_txt),
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    logging.info("Found %d issue(s) across %d bad file(s)", len(issues), len(bad_files))
    logging.info("Summary: %s", summary_json)
    logging.info("Issues JSON: %s", issues_json)
    logging.info("Issues CSV: %s", issues_csv)
    logging.info("Bad files list: %s", bad_files_txt)

    if args.fail_on_issues and issues:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

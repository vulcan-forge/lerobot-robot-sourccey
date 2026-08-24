# Sourccey dataset tools

These package-owned utilities cover the Sourccey dataset workflow:

- `combine.py` merges complete datasets and reproducible episode samples.
- `audit_dataset_consistency.py` checks metadata, statistics, intervention data, and `z.pos`.
- `audit_video_decode_errors.py` finds damaged or undecodable video files.
- `fix_dataset_consistency.py` repairs supported metadata and data consistency issues.
- `remove_feature.py` removes selected features into new dataset copies.
- `repair_bad_videos_from_audit.sh` repairs files reported by the video audit.

See [`docs/datasets.md`](../../../docs/datasets.md) for the complete combine, audit,
repair, and cleanup runbook.

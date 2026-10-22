"""Compare persisted dHash fingerprints within an investigation."""
from __future__ import annotations

from itertools import combinations
from typing import Any
from uuid import UUID


def hamming_distance(left: str, right: str) -> int:
    """Return the bit distance between two 64-bit hexadecimal dHashes."""
    if len(left) != 16 or len(right) != 16:
        raise ValueError("dHash fingerprints must be 16 hexadecimal characters")
    try:
        left_value = int(left, 16)
        right_value = int(right, 16)
    except ValueError as exc:
        raise ValueError("dHash fingerprints must be hexadecimal") from exc
    return (left_value ^ right_value).bit_count()


def _fingerprints(job: Any, media: Any) -> list[dict[str, Any]]:
    result = job.result or {}
    if job.analysis_type == "perceptual_hash" and result.get("check") == "difference_hash":
        values = [{"hash": result.get("hash"), "frame_index": None, "timestamp_seconds_estimate": None}]
    elif job.analysis_type == "video_frame_fingerprints" and result.get("check") == "video_frame_fingerprints":
        values = result.get("fingerprints", [])
    else:
        return []

    valid: list[dict[str, Any]] = []
    for value in values:
        fingerprint = value.get("hash") if isinstance(value, dict) else None
        if not isinstance(fingerprint, str) or len(fingerprint) != 16:
            continue
        try:
            int(fingerprint, 16)
        except ValueError:
            continue
        valid.append({
            "hash": fingerprint.lower(),
            "frame_index": value.get("frame_index"),
            "timestamp_seconds_estimate": value.get("timestamp_seconds_estimate"),
            "media_asset_id": str(media.id),
            "filename": media.original_filename,
            "media_type": "video" if media.mime_type.startswith("video/") else "image",
        })
    return valid


def find_similarity_matches(
    assets_and_jobs: list[tuple[Any, Any]],
    *,
    max_distance: int = 10,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Find best sampled-fingerprint matches for each pair of media assets.

    Only completed image dHash and video frame-fingerprint jobs are considered.
    A match is a lead for review, not proof that two files depict the same event.
    """
    if not 0 <= max_distance <= 64:
        raise ValueError("max_distance must be between 0 and 64")
    if not 1 <= max_results <= 500:
        raise ValueError("max_results must be between 1 and 500")

    fingerprints_by_asset: dict[str, list[dict[str, Any]]] = {}
    for media, job in assets_and_jobs:
        if job.status != "completed":
            continue
        fingerprints = _fingerprints(job, media)
        if fingerprints:
            fingerprints_by_asset.setdefault(str(media.id), []).extend(fingerprints)

    matches: list[dict[str, Any]] = []
    for (left_id, left_values), (right_id, right_values) in combinations(fingerprints_by_asset.items(), 2):
        best: tuple[int, dict[str, Any], dict[str, Any]] | None = None
        for left in left_values:
            for right in right_values:
                distance = hamming_distance(left["hash"], right["hash"])
                if best is None or distance < best[0]:
                    best = (distance, left, right)
        if best is None or best[0] > max_distance:
            continue
        distance, left, right = best
        matches.append({
            "left": {key: left[key] for key in ("media_asset_id", "filename", "media_type", "frame_index", "timestamp_seconds_estimate")},
            "right": {key: right[key] for key in ("media_asset_id", "filename", "media_type", "frame_index", "timestamp_seconds_estimate")},
            "hamming_distance": distance,
            "similarity_score": round(1 - distance / 64, 4),
            "algorithm": "dhash-64-v1",
            "interpretation": "Candidate visual similarity only; review the original evidence before drawing conclusions.",
        })
    matches.sort(key=lambda item: (item["hamming_distance"], item["left"]["media_asset_id"], item["right"]["media_asset_id"]))
    return matches[:max_results]

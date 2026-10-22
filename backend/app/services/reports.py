"""Build reproducible, evidence-first investigation reports."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.services.similarity import find_similarity_matches

REPORT_SCHEMA_VERSION = "1.0"


def build_investigation_report(
    investigation: Any,
    media_assets: list[Any],
    analysis_jobs: list[Any],
    events_by_job: dict[str, list[Any]],
    *,
    similarity_max_distance: int = 10,
    similarity_limit: int = 100,
) -> dict[str, Any]:
    """Create a JSON-safe snapshot from persisted investigation records."""
    assets_by_id = {str(asset.id): asset for asset in media_assets}
    jobs_by_asset: dict[str, list[Any]] = {}
    for job in analysis_jobs:
        jobs_by_asset.setdefault(str(job.media_asset_id), []).append(job)

    media_records: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    analysis_counts: Counter[str] = Counter()
    integrity_mismatches: list[dict[str, Any]] = []
    completed_fingerprints: list[tuple[Any, Any]] = []
    job_records: list[dict[str, Any]] = []

    for asset in sorted(media_assets, key=lambda item: (item.created_at or datetime.min.replace(tzinfo=timezone.utc), str(item.id))):
        asset_id = str(asset.id)
        media_jobs = sorted(
            jobs_by_asset.get(asset_id, []),
            key=lambda job: (job.created_at or datetime.min.replace(tzinfo=timezone.utc), str(job.id)),
        )
        media_records.append({
            "id": asset_id,
            "filename": asset.original_filename,
            "mime_type": asset.mime_type,
            "size_bytes": asset.size_bytes,
            "sha256": asset.sha256,
            "created_at": _iso(asset.created_at),
            "analysis_job_count": len(media_jobs),
        })
        for job in media_jobs:
            status_counts[job.status] += 1
            analysis_counts[job.analysis_type] += 1
            result = job.result if isinstance(job.result, dict) else None
            if job.status == "completed" and job.analysis_type in {"perceptual_hash", "video_frame_fingerprints"}:
                completed_fingerprints.append((asset, job))
            if job.status == "completed" and job.analysis_type == "integrity_check" and result and result.get("matches") is False:
                integrity_mismatches.append({
                    "media_asset_id": asset_id,
                    "filename": asset.original_filename,
                    "analysis_job_id": str(job.id),
                    "finding": "sha256_mismatch",
                    "severity": "review_required",
                    "message": "Computed SHA-256 did not match the ingestion digest.",
                })
            events = events_by_job.get(str(job.id), [])
            job_records.append({
                "id": str(job.id),
                "media_asset_id": asset_id,
                "analysis_type": job.analysis_type,
                "status": job.status,
                "result": result,
                "error_message": job.error_message,
                "created_at": _iso(job.created_at),
                "updated_at": _iso(job.updated_at),
                "events": [
                    {
                        "event_type": event.event_type,
                        "status": event.status,
                        "message": event.message,
                        "created_at": _iso(event.created_at),
                    }
                    for event in sorted(events, key=lambda item: (item.created_at or datetime.min.replace(tzinfo=timezone.utc), item.id))
                ],
            })

    matches = find_similarity_matches(
        completed_fingerprints,
        max_distance=similarity_max_distance,
        max_results=similarity_limit,
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "investigation": {
            "id": str(investigation.id),
            "title": investigation.title,
            "description": investigation.description,
            "status": investigation.status,
            "created_at": _iso(investigation.created_at),
            "updated_at": _iso(investigation.updated_at),
        },
        "summary": {
            "media_asset_count": len(media_assets),
            "analysis_job_count": len(analysis_jobs),
            "analysis_jobs_by_status": dict(sorted(status_counts.items())),
            "analysis_jobs_by_type": dict(sorted(analysis_counts.items())),
            "integrity_mismatch_count": len(integrity_mismatches),
            "similarity_match_count": len(matches),
        },
        "findings": {
            "integrity_mismatches": integrity_mismatches,
            "similarity_matches": matches,
        },
        "media_assets": media_records,
        "analysis_jobs": job_records,
        "methodology": {
            "integrity_check": "Compares the current file SHA-256 digest with the digest recorded at ingestion.",
            "image_similarity": "64-bit difference-hash (dHash) Hamming distance; smaller distances indicate closer fingerprints.",
            "video_similarity": "Uses sampled video-frame dHashes and may miss content between sampled frames.",
            "similarity_max_hamming_distance": similarity_max_distance,
            "limitations": [
                "This report is a snapshot of records available when it was generated.",
                "Similarity matches are candidate leads, not proof of common origin, authenticity, or manipulation.",
                "Missing metadata or provenance does not establish that media is false.",
                "This report does not include GPS coordinates or arbitrary EXIF fields.",
            ],
        },
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None

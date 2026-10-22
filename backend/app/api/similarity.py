from typing import Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import AnalysisJob, Investigation, MediaAsset
from app.services.similarity import find_similarity_matches

router = APIRouter(prefix="/api/v1", tags=["similarity search"])


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/investigations/{investigation_id}/similarity")
def search_investigation_similarity(
    investigation_id: UUID,
    max_distance: int = Query(default=10, ge=0, le=64),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """Compare completed image and sampled-video dHashes in one investigation."""
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    statement = (
        select(MediaAsset, AnalysisJob)
        .join(AnalysisJob, AnalysisJob.media_asset_id == MediaAsset.id)
        .where(
            MediaAsset.investigation_id == investigation_id,
            AnalysisJob.status == "completed",
            AnalysisJob.analysis_type.in_(["perceptual_hash", "video_frame_fingerprints"]),
        )
        .order_by(AnalysisJob.updated_at.desc())
    )
    rows = list(db.execute(statement).all())
    # Keep only the newest completed fingerprint job for each asset and type.
    seen: set[tuple[str, str]] = set()
    latest_rows = []
    for media, job in rows:
        key = (str(media.id), job.analysis_type)
        if key in seen:
            continue
        seen.add(key)
        latest_rows.append((media, job))

    matches = find_similarity_matches(latest_rows, max_distance=max_distance, max_results=limit)
    return {
        "investigation_id": str(investigation_id),
        "algorithm": "dhash-64-v1",
        "max_hamming_distance": max_distance,
        "result_count": len(matches),
        "matches": matches,
        "limitations": [
            "Only completed perceptual_hash and video_frame_fingerprints jobs are compared.",
            "Video comparisons use sampled frames and can miss relevant content between samples.",
            "Similarity scores are not probabilities and do not establish provenance or manipulation.",
        ],
    }

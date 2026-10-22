from typing import Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import AnalysisJob, MediaAsset
from app.schemas.jobs import AnalysisJobCreate, AnalysisJobRead
from app.tasks.analysis import run_analysis_job

router = APIRouter(prefix="/api/v1", tags=["analysis jobs"])


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post(
    "/media/{media_asset_id}/analysis-jobs",
    response_model=AnalysisJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis_job(
    media_asset_id: UUID,
    payload: AnalysisJobCreate,
    db: Session = Depends(get_db),
) -> AnalysisJob:
    media = db.get(MediaAsset, media_asset_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media asset not found")

    image_only_analysis = {"metadata_extract", "perceptual_hash"}
    if (
        payload.analysis_type in image_only_analysis
        and not media.mime_type.startswith("image/")
    ):
        raise HTTPException(
            status_code=422,
            detail=f"{payload.analysis_type} currently supports image files only",
        )

    job = AnalysisJob(
        media_asset_id=media_asset_id,
        analysis_type=payload.analysis_type,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        run_analysis_job.delay(str(job.id))
    except Exception as exc:
        job.status = "failed"
        job.error_message = "Could not enqueue analysis job; check Redis availability"
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="Analysis queue unavailable",
        ) from exc

    return job


@router.get(
    "/analysis-jobs/{job_id}",
    response_model=AnalysisJobRead,
)
def get_analysis_job(
    job_id: UUID,
    db: Session = Depends(get_db),
) -> AnalysisJob:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    return job

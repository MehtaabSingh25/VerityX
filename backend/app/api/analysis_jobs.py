from typing import Annotated, Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.core.investigation_access import verify_investigation_token
from app.core.observability import (
    ANALYSIS_JOB_ENQUEUE_FAILURES, ANALYSIS_JOBS_SUBMITTED,
)
from app.models import AnalysisJob, AnalysisJobEvent, MediaAsset
from app.schemas.jobs import (
    AnalysisJobCreate,
    AnalysisJobEventRead,
    AnalysisJobRead,
)
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
    investigation_token: Annotated[str | None, Header(alias="X-Investigation-Token")] = None,
    db: Session = Depends(get_db),
) -> AnalysisJob:
    media = db.get(MediaAsset, media_asset_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    verify_investigation_token(media.investigation, investigation_token)

    image_only_analysis = {"metadata_extract", "perceptual_hash"}
    video_only_analysis = {"video_metadata", "video_frame_fingerprints"}
    if (
        payload.analysis_type in image_only_analysis
        and not media.mime_type.startswith("image/")
    ):
        raise HTTPException(
            status_code=422,
            detail=f"{payload.analysis_type} currently supports image files only",
        )
    if (
        payload.analysis_type in video_only_analysis
        and not media.mime_type.startswith("video/")
    ):
        raise HTTPException(
            status_code=422,
            detail=f"{payload.analysis_type} currently supports video files only",
        )

    job = AnalysisJob(
        media_asset_id=media_asset_id,
        analysis_type=payload.analysis_type,
        status="queued",
    )
    db.add(job)
    db.flush()
    db.add(AnalysisJobEvent(
        analysis_job_id=job.id,
        event_type="queued",
        status="queued",
        message="Analysis job accepted and queued.",
    ))
    db.commit()
    db.refresh(job)
    ANALYSIS_JOBS_SUBMITTED.labels(payload.analysis_type).inc()

    try:
        run_analysis_job.delay(str(job.id))
    except Exception as exc:
        ANALYSIS_JOB_ENQUEUE_FAILURES.labels(payload.analysis_type).inc()
        job.status = "failed"
        job.error_message = "Could not enqueue analysis job; check Redis availability"
        db.add(AnalysisJobEvent(
            analysis_job_id=job.id,
            event_type="enqueue_failed",
            status="failed",
            message="Analysis queue unavailable; the job was not enqueued.",
        ))
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
    investigation_token: Annotated[str | None, Header(alias="X-Investigation-Token")] = None,
    db: Session = Depends(get_db),
) -> AnalysisJob:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    verify_investigation_token(job.media_asset.investigation, investigation_token)
    return job


@router.get(
    "/analysis-jobs/{job_id}/events",
    response_model=list[AnalysisJobEventRead],
)
def list_analysis_job_events(
    job_id: UUID,
    investigation_token: Annotated[str | None, Header(alias="X-Investigation-Token")] = None,
    db: Session = Depends(get_db),
) -> list[AnalysisJobEvent]:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    verify_investigation_token(job.media_asset.investigation, investigation_token)

    statement = (
        select(AnalysisJobEvent)
        .where(AnalysisJobEvent.analysis_job_id == job_id)
        .order_by(AnalysisJobEvent.created_at, AnalysisJobEvent.id)
    )
    return list(db.scalars(statement).all())

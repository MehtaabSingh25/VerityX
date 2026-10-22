import re
from typing import Annotated, Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.core.investigation_access import verify_investigation_token
from app.core.observability import (
    ANALYSIS_JOB_ENQUEUE_FAILURES, ANALYSIS_JOBS_SUBMITTED,
)
from app.models import AnalysisJob, AnalysisJobEvent, MediaAsset, OutboxMessage
from app.schemas.jobs import (
    AnalysisJobCreate,
    AnalysisJobEventRead,
    AnalysisJobRead,
)
from app.outbox import publish_outbox_message

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
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
) -> AnalysisJob:
    media = db.get(MediaAsset, media_asset_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    verify_investigation_token(media.investigation, investigation_token)

    if idempotency_key is not None:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key):
            raise HTTPException(
                status_code=400,
                detail="Invalid Idempotency-Key; use 1-128 letters, digits, '.', '_', ':', or '-'",
            )
        existing = db.scalar(
            select(AnalysisJob).where(
                AnalysisJob.media_asset_id == media_asset_id,
                AnalysisJob.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.analysis_type != payload.analysis_type:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used for a different analysis type",
                )
            return existing

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
        idempotency_key=idempotency_key,
        status="queued",
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:
        # A concurrent request may have inserted the same key after our lookup.
        db.rollback()
        if idempotency_key is not None:
            existing = db.scalar(
                select(AnalysisJob).where(
                    AnalysisJob.media_asset_id == media_asset_id,
                    AnalysisJob.idempotency_key == idempotency_key,
                )
            )
            if existing is not None and existing.analysis_type == payload.analysis_type:
                return existing
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used for a different analysis type",
                ) from exc
        raise HTTPException(status_code=409, detail="Could not create a unique analysis job") from exc
    db.add(AnalysisJobEvent(
        analysis_job_id=job.id,
        event_type="queued",
        status="queued",
        message="Analysis job accepted and queued.",
    ))
    outbox_message = OutboxMessage(
        analysis_job_id=job.id,
        task_name="verityx.run_analysis_job",
        payload={"job_id": str(job.id)},
        status="pending",
    )
    db.add(outbox_message)
    # The job and its publish request commit atomically. A separate relay keeps
    # retrying if Redis is temporarily unavailable after this transaction.
    db.commit()
    db.refresh(job)
    db.refresh(outbox_message)
    ANALYSIS_JOBS_SUBMITTED.labels(payload.analysis_type).inc()

    published = publish_outbox_message(outbox_message.id, db)
    db.refresh(outbox_message)
    if not published and outbox_message.last_error:
        ANALYSIS_JOB_ENQUEUE_FAILURES.labels(payload.analysis_type).inc()
    db.refresh(job)
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

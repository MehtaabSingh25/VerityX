from typing import Annotated, Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.core.investigation_access import verify_investigation_token
from app.models import AnalysisJob, AnalysisJobEvent, Investigation, MediaAsset
from app.services.reports import build_investigation_report

router = APIRouter(prefix="/api/v1", tags=["investigation reports"])


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/investigations/{investigation_id}/report")
def get_investigation_report(
    investigation_id: UUID,
    max_distance: int = Query(default=10, ge=0, le=64),
    similarity_limit: int = Query(default=100, ge=1, le=500),
    investigation_token: Annotated[str | None, Header(alias="X-Investigation-Token")] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Generate a JSON evidence report from the investigation's stored records."""
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    verify_investigation_token(investigation, investigation_token)

    media_assets = list(db.scalars(
        select(MediaAsset)
        .where(MediaAsset.investigation_id == investigation_id)
        .order_by(MediaAsset.created_at, MediaAsset.id)
    ).all())
    media_ids = [asset.id for asset in media_assets]
    jobs: list[AnalysisJob] = []
    if media_ids:
        jobs = list(db.scalars(
            select(AnalysisJob)
            .where(AnalysisJob.media_asset_id.in_(media_ids))
            .order_by(AnalysisJob.created_at, AnalysisJob.id)
        ).all())

    job_ids = [job.id for job in jobs]
    events_by_job: dict[str, list[AnalysisJobEvent]] = {}
    if job_ids:
        events = db.scalars(
            select(AnalysisJobEvent)
            .where(AnalysisJobEvent.analysis_job_id.in_(job_ids))
            .order_by(AnalysisJobEvent.created_at, AnalysisJobEvent.id)
        ).all()
        for event in events:
            events_by_job.setdefault(str(event.analysis_job_id), []).append(event)

    return build_investigation_report(
        investigation,
        media_assets,
        jobs,
        events_by_job,
        similarity_max_distance=max_distance,
        similarity_limit=similarity_limit,
    )

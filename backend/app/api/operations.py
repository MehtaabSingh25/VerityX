"""Database-backed operational summary for analysis jobs."""

from datetime import datetime, timezone
from typing import Iterator

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import AnalysisJob, AnalysisJobEvent

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/summary")
def operations_summary(db: Session = Depends(get_db)) -> dict:
    """Return bounded, database-backed job and lifecycle counts.

    This endpoint contains no media content or error-message text. Restrict it
    to trusted operators if the API is exposed beyond a local environment.
    """
    status_rows = db.execute(
        select(AnalysisJob.status, func.count(AnalysisJob.id)).group_by(AnalysisJob.status)
    ).all()
    type_rows = db.execute(
        select(AnalysisJob.analysis_type, func.count(AnalysisJob.id))
        .group_by(AnalysisJob.analysis_type)
    ).all()
    event_rows = db.execute(
        select(AnalysisJobEvent.event_type, func.count(AnalysisJobEvent.id))
        .group_by(AnalysisJobEvent.event_type)
    ).all()

    jobs_by_status = {str(status): int(count) for status, count in status_rows}
    jobs_by_type = {str(analysis_type): int(count) for analysis_type, count in type_rows}
    events_by_type = {str(event_type): int(count) for event_type, count in event_rows}
    total_jobs = sum(jobs_by_status.values())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_jobs": total_jobs,
        "jobs_by_status": jobs_by_status,
        "jobs_by_analysis_type": jobs_by_type,
        "lifecycle_events_by_type": events_by_type,
    }

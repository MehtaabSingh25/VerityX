"""Regression tests for retry and duplicate-delivery behavior in the worker."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from celery.exceptions import Retry
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import AnalysisJob, AnalysisJobEvent, Investigation, MediaAsset


@pytest.fixture
def worker_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Provide an isolated SQLite database for the real task function."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    import app.tasks.analysis as task_module
    from app.core.config import settings

    monkeypatch.setattr(task_module, "SessionLocal", session_local)
    monkeypatch.setattr(settings, "media_storage_dir", str(tmp_path / "media"))

    with session_local() as db:
        investigation = Investigation(title="Worker reliability test")
        db.add(investigation)
        db.flush()
        media = MediaAsset(
            investigation_id=investigation.id,
            original_filename="sample.png",
            sha256="a" * 64,
            mime_type="image/png",
            size_bytes=10,
            storage_key="sample.png",
        )
        db.add(media)
        db.flush()
        job = AnalysisJob(
            media_asset_id=media.id,
            analysis_type="metadata_extract",
            status="queued",
        )
        db.add(job)
        db.commit()
        job_id = job.id

    yield {"session_local": session_local, "job_id": job_id, "engine": engine}
    engine.dispose()


def _read_job(session_local: Any, job_id: UUID) -> tuple[AnalysisJob, list[AnalysisJobEvent]]:
    with session_local() as db:
        job = db.get(AnalysisJob, job_id)
        assert job is not None
        events = list(
            db.scalars(
                select(AnalysisJobEvent)
                .where(AnalysisJobEvent.analysis_job_id == job_id)
                .order_by(AnalysisJobEvent.id)
            )
        )
        return job, events


def test_transient_oserror_schedules_retry_and_requeues_job(
    worker_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.analysis as task_module

    def fail_transiently(_path: Path) -> dict[str, Any]:
        raise OSError("temporary storage read failure")

    monkeypatch.setattr(task_module, "extract_image_metadata", fail_transiently)

    def raise_retry(*, exc: BaseException) -> None:
        raise Retry(exc=exc)

    # Avoid publishing to a real Redis broker in this isolated unit test.
    monkeypatch.setattr(task_module.run_analysis_job, "retry", raise_retry)

    with pytest.raises(Retry):
        task_module.run_analysis_job.run(str(worker_db["job_id"]))

    job, events = _read_job(worker_db["session_local"], worker_db["job_id"])
    assert job.status == "queued"
    assert job.error_message == "temporary storage read failure"
    assert [event.event_type for event in events] == ["started", "retry_scheduled"]


def test_permanent_analysis_error_marks_job_failed(
    worker_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.analysis as task_module

    def fail_permanently(_path: Path) -> dict[str, Any]:
        raise ValueError("unsupported image content")

    monkeypatch.setattr(task_module, "extract_image_metadata", fail_permanently)

    with pytest.raises(ValueError, match="unsupported image content"):
        task_module.run_analysis_job.run(str(worker_db["job_id"]))

    job, events = _read_job(worker_db["session_local"], worker_db["job_id"])
    assert job.status == "failed"
    assert job.error_message == "unsupported image content"
    assert [event.event_type for event in events] == ["started", "failed"]


def test_completed_job_duplicate_delivery_returns_saved_result_without_reprocessing(
    worker_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.analysis as task_module

    expected_result = {"check": "image_metadata", "width": 12, "height": 8}
    with worker_db["session_local"]() as db:
        job = db.get(AnalysisJob, worker_db["job_id"])
        assert job is not None
        job.status = "completed"
        job.result = expected_result
        db.commit()

    def should_not_run(_path: Path) -> dict[str, Any]:
        raise AssertionError("completed jobs must not be processed twice")

    monkeypatch.setattr(task_module, "extract_image_metadata", should_not_run)

    result = task_module.run_analysis_job.run(str(worker_db["job_id"]))

    job, events = _read_job(worker_db["session_local"], worker_db["job_id"])
    assert result == expected_result
    assert job.status == "completed"
    assert events == []

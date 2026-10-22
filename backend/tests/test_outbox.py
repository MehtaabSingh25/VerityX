"""Tests for durable outbox publishing and broker-failure recovery."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import AnalysisJob, Investigation, MediaAsset, OutboxMessage


@pytest.fixture
def outbox_db() -> dict[str, Any]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_local() as db:
        investigation = Investigation(title="Outbox test")
        db.add(investigation)
        db.flush()
        media = MediaAsset(
            investigation_id=investigation.id,
            original_filename="sample.png",
            sha256="a" * 64,
            mime_type="image/png",
            size_bytes=1,
            storage_key="sample.png",
        )
        db.add(media)
        db.flush()
        job = AnalysisJob(media_asset_id=media.id, analysis_type="integrity_check", status="queued")
        db.add(job)
        db.flush()
        message = OutboxMessage(
            analysis_job_id=job.id,
            task_name="verityx.run_analysis_job",
            payload={"job_id": str(job.id)},
            status="pending",
        )
        db.add(message)
        db.commit()
        message_id = message.id
    yield {"engine": engine, "session_local": session_local, "message_id": message_id}
    engine.dispose()


def test_successful_publish_marks_outbox_message_published(
    outbox_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.outbox as outbox

    published: list[str] = []
    monkeypatch.setattr(outbox.run_analysis_job, "delay", lambda job_id: published.append(job_id))
    with outbox_db["session_local"]() as db:
        assert outbox.publish_outbox_message(outbox_db["message_id"], db) is True
        message = db.get(OutboxMessage, outbox_db["message_id"])
        assert message is not None
        assert message.status == "published"
        assert message.attempts == 1
        assert message.published_at is not None
        assert message.last_error is None
        assert published == [message.payload["job_id"]]


def test_broker_failure_keeps_message_pending_for_retry(
    outbox_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.outbox as outbox

    def fail_publish(_job_id: str) -> None:
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr(outbox.run_analysis_job, "delay", fail_publish)
    with outbox_db["session_local"]() as db:
        assert outbox.publish_outbox_message(outbox_db["message_id"], db) is False
        message = db.get(OutboxMessage, outbox_db["message_id"])
        assert message is not None
        assert message.status == "pending"
        assert message.attempts == 1
        assert "Redis unavailable" in (message.last_error or "")
        assert message.next_attempt_at is not None
        next_attempt = message.next_attempt_at
        if next_attempt.tzinfo is None:
            next_attempt = next_attempt.replace(tzinfo=timezone.utc)
        assert next_attempt > datetime.now(timezone.utc)


def test_stale_publishing_claim_can_be_reclaimed(
    outbox_db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.outbox as outbox

    published: list[str] = []
    monkeypatch.setattr(outbox.run_analysis_job, "delay", lambda job_id: published.append(job_id))
    with outbox_db["session_local"]() as db:
        message = db.get(OutboxMessage, outbox_db["message_id"])
        assert message is not None
        message.status = "publishing"
        message.claimed_at = datetime.now(timezone.utc) - timedelta(seconds=outbox.LEASE_SECONDS + 1)
        db.commit()
        assert outbox.publish_outbox_message(message.id, db) is True
        db.refresh(message)
        assert message.status == "published"
        assert published == [message.payload["job_id"]]

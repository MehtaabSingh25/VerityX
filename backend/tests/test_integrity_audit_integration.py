import hashlib

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    AnalysisJob,
    EvidenceAuditEvent,
    Investigation,
    MediaAsset,
)
from app.services.evidence_audit import verify_persisted_audit_chain
import app.tasks.analysis as analysis_tasks


@pytest.fixture
def worker_db(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    TestSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    media_path = tmp_path / "evidence.bin"
    content = b"VerityX integrity audit test"
    media_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    with TestSession() as db:
        investigation = Investigation(
            title="Integrity audit test",
        )
        db.add(investigation)
        db.flush()

        media = MediaAsset(
            investigation_id=investigation.id,
            original_filename="evidence.bin",
            sha256=digest,
            mime_type="application/octet-stream",
            size_bytes=len(content),
            storage_key=media_path.name,
        )
        db.add(media)
        db.flush()

        job = AnalysisJob(
            media_asset_id=media.id,
            analysis_type="integrity_check",
            status="queued",
        )
        db.add(job)
        db.commit()

        investigation_id = investigation.id
        media_id = media.id
        job_id = job.id

    monkeypatch.setattr(
        analysis_tasks,
        "SessionLocal",
        TestSession,
    )
    monkeypatch.setattr(
        analysis_tasks,
        "_media_path",
        lambda storage_key: media_path,
    )

    yield TestSession, investigation_id, media_id, job_id

    engine.dispose()


def test_successful_integrity_job_persists_audit_event(worker_db):
    TestSession, investigation_id, media_id, job_id = worker_db

    result = analysis_tasks.run_analysis_job.run(str(job_id))

    assert result["matches"] is True

    with TestSession() as db:
        job = db.get(AnalysisJob, job_id)

        assert job is not None
        assert job.status == "completed"
        assert job.result["matches"] is True

        events = list(
            db.scalars(
                select(EvidenceAuditEvent).where(
                    EvidenceAuditEvent.investigation_id
                    == investigation_id,
                    EvidenceAuditEvent.media_asset_id == media_id,
                )
            ).all()
        )

        assert len(events) == 1

        event = events[0]
        assert event.event_type == "media.integrity_check.completed"

        # event_data stores the complete event payload directly.
        audit_record = event.event_data

        assert audit_record["event_type"] == (
            "media.integrity_check.completed"
        )
        assert audit_record["investigation_id"] == str(investigation_id)
        assert audit_record["media_asset_id"] == str(media_id)
        assert audit_record["sequence_number"] == event.sequence_number

        # The integrity result is nested inside the event's event_data.
        audit_payload = audit_record["event_data"]

        assert audit_payload["analysis_job_id"] == str(job_id)
        assert audit_payload["matches"] is True
        assert (
            audit_payload["expected_sha256"]
            == result["expected_sha256"]
        )
        assert (
            audit_payload["actual_sha256"]
            == result["actual_sha256"]
        )

        # Verify the persisted hash chain.
        chain = verify_persisted_audit_chain(
            db,
            investigation_id,
        )
        assert chain["valid"] is True
        assert chain["event_count"] == 1

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Investigation, MediaAsset
from app.services.evidence_audit import (
    append_audit_event,
    verify_persisted_audit_chain,
)


@pytest.fixture
def audit_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    with SessionLocal() as db:
        yield db

    engine.dispose()


def _investigation(db, title="Audit test"):
    investigation = Investigation(title=title)
    db.add(investigation)
    db.flush()
    return investigation


def test_appending_events_creates_ordered_hash_chain(audit_db):
    investigation = _investigation(audit_db)

    first = append_audit_event(
        audit_db,
        investigation_id=investigation.id,
        event_type="evidence_uploaded",
        event_data={"sha256": "a" * 64},
    )
    second = append_audit_event(
        audit_db,
        investigation_id=investigation.id,
        event_type="integrity_checked",
        event_data={"matches": True},
    )
    audit_db.commit()

    assert first.sequence_number == 1
    assert second.sequence_number == 2
    assert second.previous_hash == first.event_hash

    result = verify_persisted_audit_chain(audit_db, investigation.id)
    assert result["valid"] is True
    assert result["event_count"] == 2


def test_persisted_chain_detects_modified_event(audit_db):
    investigation = _investigation(audit_db)
    record = append_audit_event(
        audit_db,
        investigation_id=investigation.id,
        event_type="evidence_uploaded",
        event_data={"sha256": "a" * 64},
    )
    audit_db.commit()

    record.event_data["event_type"] = "tampered"
    audit_db.commit()

    result = verify_persisted_audit_chain(audit_db, investigation.id)
    assert result["valid"] is False
    assert result["reason"] == "event_hash_mismatch"


def test_asset_from_another_investigation_is_rejected(audit_db):
    first_investigation = _investigation(audit_db, "First")
    second_investigation = _investigation(audit_db, "Second")

    asset = MediaAsset(
        investigation_id=second_investigation.id,
        original_filename="evidence.png",
        sha256="a" * 64,
        mime_type="image/png",
        size_bytes=1,
        storage_key="test/evidence.png",
    )
    audit_db.add(asset)
    audit_db.flush()

    with pytest.raises(ValueError, match="does not belong"):
        append_audit_event(
            audit_db,
            investigation_id=first_investigation.id,
            media_asset_id=asset.id,
            event_type="evidence_uploaded",
            event_data={"sha256": asset.sha256},
        )


def test_chain_detects_deleted_middle_event(audit_db):
    investigation = _investigation(audit_db)

    for index in range(3):
        append_audit_event(
            audit_db,
            investigation_id=investigation.id,
            event_type="test_event",
            event_data={"index": index},
        )
    audit_db.commit()

    from app.models import EvidenceAuditEvent

    middle = (
        audit_db.query(EvidenceAuditEvent)
        .filter_by(
            investigation_id=investigation.id,
            sequence_number=2,
        )
        .one()
    )
    audit_db.delete(middle)
    audit_db.commit()

    result = verify_persisted_audit_chain(audit_db, investigation.id)
    assert result["valid"] is False
    assert result["reason"] in {"previous_hash_mismatch", "sequence_gap"}

"""Deterministic hashing and verification for evidence audit chains."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EvidenceAuditEvent, Investigation, MediaAsset

GENESIS_HASH = "0" * 64


def canonicalize_event(event: dict[str, Any]) -> bytes:
    """Serialize event data deterministically for cryptographic hashing."""
    return json.dumps(
        event,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_event_hash(
    event: dict[str, Any],
    previous_hash: str = GENESIS_HASH,
) -> str:
    """Hash an event together with its predecessor's digest."""
    if len(previous_hash) != 64:
        raise ValueError("previous_hash must be a 64-character SHA-256 hex digest")

    try:
        bytes.fromhex(previous_hash)
    except ValueError as exc:
        raise ValueError("previous_hash must be hexadecimal") from exc

    envelope = {
        "event": event,
        "previous_hash": previous_hash,
    }
    return hashlib.sha256(canonicalize_event(envelope)).hexdigest()


def verify_event_chain(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify event hashes and predecessor links in chronological order.

    Each event must contain ``event`` (the event payload), ``previous_hash``,
    and ``event_hash``. The first event must reference GENESIS_HASH.
    """
    expected_previous_hash = GENESIS_HASH

    for index, record in enumerate(events):
        event = record.get("event")
        previous_hash = record.get("previous_hash")
        recorded_hash = record.get("event_hash")

        if not isinstance(event, dict):
            return {
                "valid": False,
                "invalid_index": index,
                "reason": "invalid_event_payload",
            }

        if previous_hash != expected_previous_hash:
            return {
                "valid": False,
                "invalid_index": index,
                "reason": "previous_hash_mismatch",
            }

        calculated_hash = compute_event_hash(event, previous_hash)
        if recorded_hash != calculated_hash:
            return {
                "valid": False,
                "invalid_index": index,
                "reason": "event_hash_mismatch",
            }

        expected_previous_hash = calculated_hash

    return {
        "valid": True,
        "event_count": len(events),
        "head_hash": expected_previous_hash,
    }


def append_audit_event(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    event_type: str,
    event_data: dict[str, Any],
    media_asset_id: uuid.UUID | None = None,
) -> EvidenceAuditEvent:
    """Append an audit event while serializing writers per investigation."""
    # Lock the parent row to serialize concurrent PostgreSQL transactions.
    investigation = db.execute(
        select(Investigation)
        .where(Investigation.id == investigation_id)
        .with_for_update()
    ).scalar_one_or_none()

    if investigation is None:
        raise ValueError("Investigation not found")

    if media_asset_id is not None:
        media = db.get(MediaAsset, media_asset_id)
        if media is None or media.investigation_id != investigation_id:
            raise ValueError("Media asset does not belong to investigation")

    latest = db.execute(
        select(EvidenceAuditEvent)
        .where(EvidenceAuditEvent.investigation_id == investigation_id)
        .order_by(EvidenceAuditEvent.sequence_number.desc())
        .limit(1)
    ).scalar_one_or_none()

    previous_hash = latest.event_hash if latest else GENESIS_HASH
    sequence_number = latest.sequence_number + 1 if latest else 1

    event = {
        "investigation_id": str(investigation_id),
        "media_asset_id": str(media_asset_id) if media_asset_id else None,
        "sequence_number": sequence_number,
        "event_type": event_type,
        "event_data": event_data,
    }
    event_hash = compute_event_hash(event, previous_hash)

    record = EvidenceAuditEvent(
        investigation_id=investigation_id,
        media_asset_id=media_asset_id,
        sequence_number=sequence_number,
        event_type=event_type,
        event_data=event,
        previous_hash=previous_hash,
        event_hash=event_hash,
    )
    db.add(record)
    db.flush()
    return record


def verify_persisted_audit_chain(
    db: Session,
    investigation_id: uuid.UUID,
) -> dict[str, Any]:
    """Verify the persisted audit chain in sequence-number order."""
    rows = db.execute(
        select(EvidenceAuditEvent)
        .where(EvidenceAuditEvent.investigation_id == investigation_id)
        .order_by(EvidenceAuditEvent.sequence_number.asc())
    ).scalars().all()

    records = [
        {
            "event": row.event_data,
            "previous_hash": row.previous_hash,
            "event_hash": row.event_hash,
        }
        for row in rows
    ]
    result = verify_event_chain(records)

    # Detect gaps/reordered rows, including deletion of a middle event.
    if result["valid"]:
        expected_sequences = list(range(1, len(rows) + 1))
        actual_sequences = [row.sequence_number for row in rows]
        if actual_sequences != expected_sequences:
            return {
                "valid": False,
                "invalid_index": next(
                    index
                    for index, (actual, expected) in enumerate(
                        zip(actual_sequences, expected_sequences)
                    )
                    if actual != expected
                ),
                "reason": "sequence_gap",
            }

    return result

from app.services.evidence_audit import (
    GENESIS_HASH,
    compute_event_hash,
    verify_event_chain,
)


def _record(event, previous_hash):
    return {
        "event": event,
        "previous_hash": previous_hash,
        "event_hash": compute_event_hash(event, previous_hash),
    }


def test_event_hash_is_deterministic():
    event = {"event_type": "evidence_uploaded", "size_bytes": 42}

    assert compute_event_hash(event) == compute_event_hash(
        {"size_bytes": 42, "event_type": "evidence_uploaded"}
    )


def test_verifies_valid_chain():
    first = _record({"event_type": "evidence_uploaded"}, GENESIS_HASH)
    second = _record(
        {"event_type": "integrity_checked", "matches": True},
        first["event_hash"],
    )

    result = verify_event_chain([first, second])

    assert result["valid"] is True
    assert result["event_count"] == 2
    assert result["head_hash"] == second["event_hash"]


def test_detects_modified_event():
    record = _record({"event_type": "evidence_uploaded"}, GENESIS_HASH)
    record["event"]["event_type"] = "evidence_deleted"

    result = verify_event_chain([record])

    assert result["valid"] is False
    assert result["invalid_index"] == 0
    assert result["reason"] == "event_hash_mismatch"


def test_detects_broken_link():
    first = _record({"event_type": "evidence_uploaded"}, GENESIS_HASH)
    second = _record(
        {"event_type": "integrity_checked"},
        "a" * 64,
    )

    result = verify_event_chain([first, second])

    assert result["valid"] is False
    assert result["invalid_index"] == 1
    assert result["reason"] == "previous_hash_mismatch"


def test_empty_chain_is_valid():
    result = verify_event_chain([])

    assert result["valid"] is True
    assert result["event_count"] == 0
    assert result["head_hash"] == GENESIS_HASH

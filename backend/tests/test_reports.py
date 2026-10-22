from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.reports import build_investigation_report

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_report_summarizes_assets_jobs_events_and_similarity():
    investigation_id = uuid4()
    media_id = uuid4()
    job_id = uuid4()
    investigation = SimpleNamespace(
        id=investigation_id, title="Case 1", description="Test case", status="open",
        created_at=NOW, updated_at=NOW,
    )
    media = SimpleNamespace(
        id=media_id, original_filename="photo.png", mime_type="image/png",
        size_bytes=128, sha256="a" * 64, created_at=NOW,
    )
    job = SimpleNamespace(
        id=job_id, media_asset_id=media_id, analysis_type="integrity_check",
        status="completed", result={"check": "sha256_integrity", "matches": False},
        error_message=None, created_at=NOW, updated_at=NOW,
    )
    event = SimpleNamespace(
        id=1, event_type="completed", status="completed", message="Finished", created_at=NOW,
    )

    report = build_investigation_report(
        investigation, [media], [job], {str(job_id): [event]}
    )

    assert report["report_schema_version"] == "1.0"
    assert report["summary"]["media_asset_count"] == 1
    assert report["summary"]["analysis_jobs_by_status"] == {"completed": 1}
    assert report["summary"]["integrity_mismatch_count"] == 1
    assert report["findings"]["integrity_mismatches"][0]["finding"] == "sha256_mismatch"
    assert report["analysis_jobs"][0]["events"][0]["event_type"] == "completed"
    assert all("gps" not in key.lower() for key in report["media_assets"][0])


def test_empty_investigation_report_has_zero_counts():
    investigation = SimpleNamespace(
        id=uuid4(), title="Empty", description=None, status="open",
        created_at=NOW, updated_at=NOW,
    )
    report = build_investigation_report(investigation, [], [], {})

    assert report["summary"]["media_asset_count"] == 0
    assert report["summary"]["analysis_job_count"] == 0
    assert report["findings"]["similarity_matches"] == []

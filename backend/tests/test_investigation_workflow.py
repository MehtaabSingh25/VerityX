"""End-to-end API workflow tests using an isolated SQLite database.

These tests exercise the real FastAPI routes and analysis task function while
replacing only the Celery broker handoff. They do not require a running
PostgreSQL or Redis service.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.main import app


@pytest.fixture
def workflow_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    """Provide isolated persistence and media storage for each workflow test."""
    database_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(database_engine)
    test_session_local = sessionmaker(
        bind=database_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    import app.api.analysis_jobs as analysis_jobs_api
    import app.api.media_ingestion as media_api
    import app.api.operations as operations_api
    import app.api.reports as reports_api
    import app.api.similarity as similarity_api
    import app.outbox as outbox
    import app.tasks.analysis as analysis_tasks
    from app.core.config import settings

    for module in (
        analysis_jobs_api,
        media_api,
        operations_api,
        reports_api,
        similarity_api,
        analysis_tasks,
    ):
        monkeypatch.setattr(module, "SessionLocal", test_session_local)
    monkeypatch.setattr(settings, "media_storage_dir", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "api_key", None)

    # Execute the real task body synchronously instead of requiring a broker.
    monkeypatch.setattr(
        outbox.run_analysis_job,
        "delay",
        lambda job_id: outbox.run_analysis_job.run(job_id),
    )

    with TestClient(app) as client:
        yield client

    database_engine.dispose()


def _png_bytes() -> bytes:
    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (24, 16), color=(35, 80, 120)).save(output, format="PNG")
    return output.getvalue()


def test_upload_analysis_events_and_report_workflow(workflow_client: TestClient) -> None:
    client = workflow_client

    investigation_response = client.post(
        "/api/v1/investigations",
        json={
            "title": "Workflow integration test",
            "description": "Exercise upload through report generation.",
        },
    )
    assert investigation_response.status_code == 201
    investigation_id = investigation_response.json()["id"]
    investigation_headers = {"X-Investigation-Token": investigation_response.json()["access_token"]}

    upload_response = client.post(
        f"/api/v1/investigations/{investigation_id}/media",
        files={"file": ("evidence.png", _png_bytes(), "image/png")},
        headers=investigation_headers,
    )
    assert upload_response.status_code == 201, upload_response.text
    media = upload_response.json()
    assert media["sha256"]
    assert media["size_bytes"] > 0

    job_response = client.post(
        f"/api/v1/media/{media['id']}/analysis-jobs",
        json={"analysis_type": "integrity_check"},
        headers=investigation_headers,
    )
    assert job_response.status_code == 202, job_response.text
    job_id = job_response.json()["id"]

    persisted_job_response = client.get(f"/api/v1/analysis-jobs/{job_id}", headers=investigation_headers)
    assert persisted_job_response.status_code == 200
    job = persisted_job_response.json()
    assert job["status"] == "completed"
    assert job["result"]["check"] == "sha256_integrity"
    assert job["result"]["matches"] is True

    events_response = client.get(f"/api/v1/analysis-jobs/{job_id}/events", headers=investigation_headers)
    assert events_response.status_code == 200
    event_types = [event["event_type"] for event in events_response.json()]
    assert event_types[0] == "queued"
    assert "started" in event_types
    assert event_types[-1] == "completed"

    report_response = client.get(
        f"/api/v1/investigations/{investigation_id}/report",
        headers=investigation_headers,
    )
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["summary"]["media_asset_count"] == 1
    assert report["summary"]["analysis_job_count"] == 1
    assert report["summary"]["analysis_jobs_by_status"] == {"completed": 1}
    assert report["analysis_jobs"][0]["result"]["matches"] is True
    assert report["media_assets"][0]["sha256"] == media["sha256"]

    operations_response = client.get("/api/v1/operations/summary")
    assert operations_response.status_code == 200
    operations = operations_response.json()
    assert operations["total_jobs"] == 1
    assert operations["jobs_by_status"] == {"completed": 1}
    assert operations["jobs_by_analysis_type"] == {"integrity_check": 1}
    assert operations["lifecycle_events_by_type"]["completed"] == 1
    assert "generated_at" in operations


def test_report_returns_not_found_for_unknown_investigation(
    workflow_client: TestClient,
) -> None:
    response = workflow_client.get(
        "/api/v1/investigations/00000000-0000-0000-0000-000000000001/report"
    )
    assert response.status_code == 404


def test_investigation_token_is_required_and_scoped(workflow_client: TestClient) -> None:
    client = workflow_client
    first = client.post("/api/v1/investigations", json={"title": "First case"})
    second = client.post("/api/v1/investigations", json={"title": "Second case"})
    assert first.status_code == second.status_code == 201

    first_id = first.json()["id"]
    second_id = second.json()["id"]
    first_headers = {"X-Investigation-Token": first.json()["access_token"]}

    missing = client.get(f"/api/v1/investigations/{first_id}/report")
    assert missing.status_code == 403

    cross_case_upload = client.post(
        f"/api/v1/investigations/{second_id}/media",
        files={"file": ("evidence.png", _png_bytes(), "image/png")},
        headers=first_headers,
    )
    assert cross_case_upload.status_code == 403

    own_report = client.get(
        f"/api/v1/investigations/{first_id}/report", headers=first_headers
    )
    assert own_report.status_code == 200


def test_service_key_can_rotate_investigation_token(workflow_client: TestClient) -> None:
    client = workflow_client
    created = client.post("/api/v1/investigations", json={"title": "Rotate token"})
    assert created.status_code == 201
    investigation_id = created.json()["id"]
    old_headers = {"X-Investigation-Token": created.json()["access_token"]}

    rotated = client.post(
        f"/api/v1/investigations/{investigation_id}/access-token/rotate"
    )
    assert rotated.status_code == 200
    new_headers = {"X-Investigation-Token": rotated.json()["access_token"]}

    old_access = client.get(
        f"/api/v1/investigations/{investigation_id}/report", headers=old_headers
    )
    new_access = client.get(
        f"/api/v1/investigations/{investigation_id}/report", headers=new_headers
    )
    assert old_access.status_code == 403
    assert new_access.status_code == 200


def test_analysis_job_submission_is_idempotent(workflow_client: TestClient) -> None:
    client = workflow_client
    created = client.post("/api/v1/investigations", json={"title": "Idempotency test"})
    assert created.status_code == 201
    investigation_id = created.json()["id"]
    headers = {"X-Investigation-Token": created.json()["access_token"]}
    uploaded = client.post(
        f"/api/v1/investigations/{investigation_id}/media",
        files={"file": ("evidence.png", _png_bytes(), "image/png")},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    media_id = uploaded.json()["id"]
    headers["Idempotency-Key"] = "integrity-check-001"

    first = client.post(
        f"/api/v1/media/{media_id}/analysis-jobs",
        json={"analysis_type": "integrity_check"},
        headers=headers,
    )
    second = client.post(
        f"/api/v1/media/{media_id}/analysis-jobs",
        json={"analysis_type": "integrity_check"},
        headers=headers,
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]

    conflict = client.post(
        f"/api/v1/media/{media_id}/analysis-jobs",
        json={"analysis_type": "metadata_extract"},
        headers=headers,
    )
    assert conflict.status_code == 409

    summary = client.get("/api/v1/operations/summary")
    assert summary.status_code == 200
    assert summary.json()["total_jobs"] == 1


def test_analysis_job_idempotency_key_format_is_validated(
    workflow_client: TestClient,
) -> None:
    client = workflow_client
    created = client.post("/api/v1/investigations", json={"title": "Invalid key test"})
    headers = {
        "X-Investigation-Token": created.json()["access_token"],
        "Idempotency-Key": "contains spaces",
    }
    uploaded = client.post(
        f"/api/v1/investigations/{created.json()['id']}/media",
        files={"file": ("evidence.png", _png_bytes(), "image/png")},
        headers={"X-Investigation-Token": created.json()["access_token"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    response = client.post(
        f"/api/v1/media/{uploaded.json()['id']}/analysis-jobs",
        json={"analysis_type": "integrity_check"},
        headers=headers,
    )
    assert response.status_code == 400



def test_investigation_list_returns_persisted_summaries_without_tokens(
    workflow_client: TestClient,
) -> None:
    client = workflow_client
    created = client.post(
        "/api/v1/investigations",
        json={"title": "Persisted case", "description": "Dashboard list test"},
    )
    assert created.status_code == 201

    response = client.get("/api/v1/investigations")
    assert response.status_code == 200, response.text
    records = response.json()
    record = next(item for item in records if item["id"] == created.json()["id"])
    assert record["title"] == "Persisted case"
    assert record["media_asset_count"] == 0
    assert "access_token" not in record
    assert "access_token_hash" not in record

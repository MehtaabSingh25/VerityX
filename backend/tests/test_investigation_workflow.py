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
    import app.api.reports as reports_api
    import app.api.similarity as similarity_api
    import app.tasks.analysis as analysis_tasks
    from app.core.config import settings

    for module in (
        analysis_jobs_api,
        media_api,
        reports_api,
        similarity_api,
        analysis_tasks,
    ):
        monkeypatch.setattr(module, "SessionLocal", test_session_local)
    monkeypatch.setattr(settings, "media_storage_dir", str(tmp_path / "media"))

    # Execute the real task body synchronously instead of requiring a broker.
    monkeypatch.setattr(
        analysis_jobs_api.run_analysis_job,
        "delay",
        lambda job_id: analysis_jobs_api.run_analysis_job.run(job_id),
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

    upload_response = client.post(
        f"/api/v1/investigations/{investigation_id}/media",
        files={"file": ("evidence.png", _png_bytes(), "image/png")},
    )
    assert upload_response.status_code == 201, upload_response.text
    media = upload_response.json()
    assert media["sha256"]
    assert media["size_bytes"] > 0

    job_response = client.post(
        f"/api/v1/media/{media['id']}/analysis-jobs",
        json={"analysis_type": "integrity_check"},
    )
    assert job_response.status_code == 202, job_response.text
    job_id = job_response.json()["id"]

    persisted_job_response = client.get(f"/api/v1/analysis-jobs/{job_id}")
    assert persisted_job_response.status_code == 200
    job = persisted_job_response.json()
    assert job["status"] == "completed"
    assert job["result"]["check"] == "sha256_integrity"
    assert job["result"]["matches"] is True

    events_response = client.get(f"/api/v1/analysis-jobs/{job_id}/events")
    assert events_response.status_code == 200
    event_types = [event["event_type"] for event in events_response.json()]
    assert event_types[0] == "queued"
    assert "started" in event_types
    assert event_types[-1] == "completed"

    report_response = client.get(
        f"/api/v1/investigations/{investigation_id}/report"
    )
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["summary"]["media_asset_count"] == 1
    assert report["summary"]["analysis_job_count"] == 1
    assert report["summary"]["analysis_jobs_by_status"] == {"completed": 1}
    assert report["analysis_jobs"][0]["result"]["matches"] is True
    assert report["media_assets"][0]["sha256"] == media["sha256"]


def test_report_returns_not_found_for_unknown_investigation(
    workflow_client: TestClient,
) -> None:
    response = workflow_client.get(
        "/api/v1/investigations/00000000-0000-0000-0000-000000000001/report"
    )
    assert response.status_code == 404

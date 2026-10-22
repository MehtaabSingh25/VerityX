"""Tests for investigation-scoped evidence listing and deletion."""
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
def evidence_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    import app.api.analysis_jobs as analysis_api
    import app.api.media_ingestion as media_api
    import app.api.operations as operations_api
    import app.api.reports as reports_api
    import app.api.similarity as similarity_api
    from app.core.config import settings

    for module in (analysis_api, media_api, operations_api, reports_api, similarity_api):
        monkeypatch.setattr(module, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "media_storage_dir", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "api_key", None)

    with TestClient(app) as client:
        yield client
    engine.dispose()


def _png() -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), color=(20, 40, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def _case(client: TestClient, title: str) -> tuple[str, dict[str, str]]:
    response = client.post("/api/v1/investigations", json={"title": title})
    assert response.status_code == 201, response.text
    payload = response.json()
    return payload["id"], {"X-Investigation-Token": payload["access_token"]}


def test_inventory_lists_persisted_media_and_requires_token(evidence_client: TestClient) -> None:
    client = evidence_client
    case_id, headers = _case(client, "Inventory list")
    upload = client.post(
        f"/api/v1/investigations/{case_id}/media",
        files={"file": ("evidence.png", _png(), "image/png")},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text

    missing_token = client.get(f"/api/v1/investigations/{case_id}/media")
    assert missing_token.status_code == 403

    listed = client.get(f"/api/v1/investigations/{case_id}/media", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == upload.json()["id"]


def test_delete_removes_evidence_and_stored_file(evidence_client: TestClient, tmp_path: Path) -> None:
    client = evidence_client
    case_id, headers = _case(client, "Inventory delete")
    upload = client.post(
        f"/api/v1/investigations/{case_id}/media",
        files={"file": ("evidence.png", _png(), "image/png")},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    asset = upload.json()
    stored_files_before = list((tmp_path / "media").glob("*"))
    assert stored_files_before

    deleted = client.delete(
        f"/api/v1/investigations/{case_id}/media/{asset['id']}", headers=headers
    )
    assert deleted.status_code == 204
    listed = client.get(f"/api/v1/investigations/{case_id}/media", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == []
    assert all(not path.exists() for path in stored_files_before)


def test_cannot_delete_media_from_another_investigation(evidence_client: TestClient) -> None:
    client = evidence_client
    first_id, first_headers = _case(client, "First inventory")
    second_id, second_headers = _case(client, "Second inventory")
    upload = client.post(
        f"/api/v1/investigations/{first_id}/media",
        files={"file": ("evidence.png", _png(), "image/png")},
        headers=first_headers,
    )
    assert upload.status_code == 201, upload.text

    response = client.delete(
        f"/api/v1/investigations/{second_id}/media/{upload.json()['id']}",
        headers=second_headers,
    )
    assert response.status_code == 404
    remaining = client.get(f"/api/v1/investigations/{first_id}/media", headers=first_headers)
    assert len(remaining.json()) == 1

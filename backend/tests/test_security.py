from fastapi import HTTPException

from app.core import security


def test_api_key_is_optional_for_local_development(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "api_key", None)
    assert security.require_api_key(None) is None


def test_api_key_rejects_missing_or_invalid_values(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "api_key", "test-secret-key")

    for supplied_key in (None, "wrong-key"):
        try:
            security.require_api_key(supplied_key)
        except HTTPException as exc:
            assert exc.status_code == 401
            assert exc.detail == "Missing or invalid API key"
        else:  # pragma: no cover - assertion guard
            raise AssertionError("Invalid API key was accepted")


def test_api_key_accepts_matching_value(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "api_key", "test-secret-key")
    assert security.require_api_key("test-secret-key") is None


def test_service_key_protects_investigation_creation_and_operations(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(security.settings, "api_key", "service-secret")
    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/investigations", json={"title": "Must be protected"}
        )
        operations_response = client.get("/api/v1/operations/summary")

    assert create_response.status_code == 401
    assert operations_response.status_code == 401

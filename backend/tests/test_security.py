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

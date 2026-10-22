"""API-key authentication for trusted VerityX API clients."""

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_api_key(
    api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Enforce the configured API key when one is configured.

    Local development and tests can run without a key. The Docker Compose
    deployment requires VERITYX_API_KEY, so deployed API routes are protected.
    """
    expected = settings.api_key
    if not expected:
        return

    if not api_key or not hmac.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

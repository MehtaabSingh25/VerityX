"""Investigation-scoped bearer tokens."""

import hashlib
import hmac
import secrets

from fastapi import HTTPException, status

from app.models import Investigation


def issue_investigation_token() -> tuple[str, str]:
    """Return a one-time plaintext token and its SHA-256 storage digest."""
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_investigation_token(
    investigation: Investigation, supplied_token: str | None
) -> None:
    """Reject missing, legacy-uninitialized, or invalid investigation tokens."""
    if not supplied_token or not investigation.access_token_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or invalid investigation token",
        )

    supplied_digest = hashlib.sha256(supplied_token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(supplied_digest, investigation.access_token_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or invalid investigation token",
        )

"""Endpoints for public-web image provenance lookups."""

from pathlib import Path
from typing import Annotated, Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.investigation_access import verify_investigation_token
from app.db.session import SessionLocal
from app.models import MediaAsset
from app.services.web_image_search import (
    SearchNotConfiguredError,
    search_public_web_image,
)

router = APIRouter(prefix="/api/v1", tags=["public web image search"])


class WebImageSearchRequest(BaseModel):
    """Optional keywords. Omit to search using an auto-generated description of the image."""

    query: str | None = Field(default=None, max_length=200)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/media/{media_asset_id}/web-image-search")
def web_image_search(
    media_asset_id: UUID,
    investigation_token: Annotated[str | None, Header(alias="X-Investigation-Token")] = None,
    payload: WebImageSearchRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Free image search over Openverse: visual similarity (no query) or keyword search (query)."""
    media = db.get(MediaAsset, media_asset_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    verify_investigation_token(media.investigation, investigation_token)
    if not media.mime_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Public-web image search supports image files only")
    if not media.storage_key:
        raise HTTPException(status_code=404, detail="Stored image file not found")

    storage_root = Path(settings.media_storage_dir).resolve()
    path = (storage_root / media.storage_key).resolve()
    try:
        path.relative_to(storage_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid media storage key") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored image file not found")

    try:
        return search_public_web_image(path, payload.query if payload else None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SearchNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        status_code = 503 if "not configured" in message or "timed out" in message or "connect" in message else 502
        raise HTTPException(status_code=status_code, detail=message) from exc

import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Annotated, Iterator

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.investigation_access import issue_investigation_token, verify_investigation_token
from app.core.security import require_api_key
from app.db.session import SessionLocal
from app.models import AnalysisJobEvent, Investigation, MediaAsset, OutboxMessage
from app.schemas.media import (
    InvestigationAccessToken, InvestigationCreate, InvestigationCreated, InvestigationListItem, MediaAssetRead,
)
from app.services.evidence_audit import append_audit_event

router = APIRouter(prefix="/api/v1", tags=["media and investigations"])
CHUNK_SIZE = 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm"}


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def detect_media_type(header: bytes) -> str | None:
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "video/mp4"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    return None


def allowed_extension(filename: str, detected_type: str) -> bool:
    extension = Path(filename).suffix.lower()
    expected = {
        "image/jpeg": {".jpg", ".jpeg"},
        "image/png": {".png"},
        "image/webp": {".webp"},
        "video/mp4": {".mp4"},
        "video/webm": {".webm"},
    }
    return extension in expected.get(detected_type, set())


@router.post(
    "/investigations",
    response_model=InvestigationCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def create_investigation(
    payload: InvestigationCreate, db: Session = Depends(get_db)
) -> dict:
    access_token, token_hash = issue_investigation_token()
    investigation = Investigation(
        title=payload.title,
        description=payload.description,
        access_token_hash=token_hash,
    )
    db.add(investigation)
    try:
        db.commit()
        db.refresh(investigation)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="Could not save investigation"
        ) from exc
    return {
        "id": investigation.id,
        "title": investigation.title,
        "description": investigation.description,
        "status": investigation.status,
        "created_at": investigation.created_at,
        "access_token": access_token,
    }


@router.get(
    "/investigations",
    response_model=list[InvestigationListItem],
    dependencies=[Depends(require_api_key)],
)
def list_investigations(db: Session = Depends(get_db)) -> list[dict]:
    """List persisted investigation summaries for the trusted workspace UI.

    The service API key is supplied server-side by the frontend proxy. Scoped
    investigation access tokens are never included in this response.
    """
    rows = db.execute(
        select(Investigation, func.count(MediaAsset.id).label("media_asset_count"))
        .outerjoin(MediaAsset, MediaAsset.investigation_id == Investigation.id)
        .group_by(Investigation.id)
        .order_by(Investigation.created_at.desc(), Investigation.id.desc())
    ).all()
    return [
        {
            "id": investigation.id,
            "title": investigation.title,
            "description": investigation.description,
            "status": investigation.status,
            "created_at": investigation.created_at,
            "media_asset_count": int(media_asset_count),
        }
        for investigation, media_asset_count in rows
    ]


@router.post(
    "/investigations/{investigation_id}/access-token/rotate",
    response_model=InvestigationAccessToken,
    dependencies=[Depends(require_api_key)],
)
def rotate_investigation_token(
    investigation_id: uuid.UUID, db: Session = Depends(get_db)
) -> dict:
    """Rotate a scoped token using the trusted service API key."""
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    access_token, token_hash = issue_investigation_token()
    investigation.access_token_hash = token_hash
    db.commit()
    return {"investigation_id": investigation.id, "access_token": access_token}


@router.post(
    "/investigations/{investigation_id}/media",
    response_model=MediaAssetRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_media(
    investigation_id: uuid.UUID,
    file: UploadFile = File(...),
    investigation_token: Annotated[str | None, Header(alias="X-Investigation-Token")] = None,
    db: Session = Depends(get_db),
) -> MediaAsset:
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    verify_investigation_token(investigation, investigation_token)

    filename = Path(file.filename or "").name.strip()
    if (
        not filename
        or len(filename) > 255
        or "\x00" in filename
        or filename in {".", ".."}
    ):
        raise HTTPException(status_code=400, detail="Invalid filename")

    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported file extension")

    storage_dir = Path(settings.media_storage_dir).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_key = f"{uuid.uuid4().hex}{extension}"
    temp_path = storage_dir / f".{uuid.uuid4().hex}.part"
    final_path = storage_dir / storage_key
    digest = hashlib.sha256()
    total_size = 0
    detected_type: str | None = None

    try:
        with temp_path.open("xb") as destination:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break

                if total_size == 0:
                    detected_type = detect_media_type(chunk[:32])
                    if detected_type is None:
                        raise HTTPException(
                            status_code=415,
                            detail="File content is not a supported image or video",
                        )
                    if not allowed_extension(filename, detected_type):
                        raise HTTPException(
                            status_code=415,
                            detail="File extension does not match detected content type",
                        )
                    declared_type = (file.content_type or "").lower()
                    if declared_type not in {
                        "",
                        "application/octet-stream",
                        detected_type,
                    }:
                        raise HTTPException(
                            status_code=415,
                            detail="Declared content type does not match file content",
                        )

                total_size += len(chunk)
                if total_size > settings.max_upload_size_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="File exceeds the configured upload size limit",
                    )

                digest.update(chunk)
                destination.write(chunk)

        if total_size == 0 or detected_type is None:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        os.replace(temp_path, final_path)
        asset = MediaAsset(
            investigation_id=investigation_id,
            original_filename=filename,
            sha256=digest.hexdigest(),
            mime_type=detected_type,
            size_bytes=total_size,
            storage_key=storage_key,
        )
        db.add(asset)

        try:
            # Ensure the asset has its database ID before creating the audit event.
            db.flush()

            append_audit_event(
                db,
                investigation_id=investigation_id,
                media_asset_id=asset.id,
                event_type="media.uploaded",
                event_data={
                    "sha256": asset.sha256,
                    "size_bytes": asset.size_bytes,
                    "mime_type": asset.mime_type,
                    "original_filename": asset.original_filename,
                },
            )

            # Persist the media asset and audit event together.
            db.commit()
            db.refresh(asset)
        except SQLAlchemyError as exc:
            db.rollback()
            final_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=503, detail="Could not save media metadata"
            ) from exc

        return asset
    finally:
        temp_path.unlink(missing_ok=True)
        await file.close()


@router.get(
    "/investigations/{investigation_id}/media",
    response_model=list[MediaAssetRead],
)
def list_investigation_media(
    investigation_id: uuid.UUID,
    investigation_token: Annotated[str | None, Header(alias="X-Investigation-Token")] = None,
    db: Session = Depends(get_db),
) -> list[MediaAsset]:
    """Return the persisted evidence inventory for one authorized investigation."""
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    verify_investigation_token(investigation, investigation_token)
    statement = (
        select(MediaAsset)
        .where(MediaAsset.investigation_id == investigation_id)
        .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
    )
    return list(db.scalars(statement).all())


@router.delete(
    "/investigations/{investigation_id}/media/{media_asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_investigation_media(
    investigation_id: uuid.UUID,
    media_asset_id: uuid.UUID,
    investigation_token: Annotated[str | None, Header(alias="X-Investigation-Token")] = None,
    db: Session = Depends(get_db),
) -> None:
    """Delete one evidence item and its analysis records from the owning case."""
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    verify_investigation_token(investigation, investigation_token)

    asset = db.scalar(
        select(MediaAsset).where(
            MediaAsset.id == media_asset_id,
            MediaAsset.investigation_id == investigation_id,
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Evidence item not found")

    storage_key = asset.storage_key
    storage_root = Path(settings.media_storage_dir).resolve()
    stored_path: Path | None = None
    if storage_key:
        candidate = (storage_root / storage_key).resolve()
        # Never unlink a path outside the configured evidence directory.
        if candidate != storage_root and storage_root in candidate.parents:
            stored_path = candidate

    try:
        job_ids = [job.id for job in asset.analysis_jobs]
        if job_ids:
            db.query(OutboxMessage).filter(OutboxMessage.analysis_job_id.in_(job_ids)).delete(
                synchronize_session=False
            )
            db.query(AnalysisJobEvent).filter(AnalysisJobEvent.analysis_job_id.in_(job_ids)).delete(
                synchronize_session=False
            )
        db.delete(asset)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Could not delete evidence item") from exc

    if stored_path is not None:
        try:
            stored_path.unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).exception(
                "Evidence metadata was deleted but stored file cleanup failed"
            )

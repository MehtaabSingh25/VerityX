import hashlib
import os
import uuid
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Investigation, MediaAsset
from app.schemas.media import InvestigationCreate, InvestigationRead, MediaAssetRead

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
    response_model=InvestigationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_investigation(
    payload: InvestigationCreate, db: Session = Depends(get_db)
) -> Investigation:
    investigation = Investigation(
        title=payload.title,
        description=payload.description,
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
    return investigation


@router.post(
    "/investigations/{investigation_id}/media",
    response_model=MediaAssetRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_media(
    investigation_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> MediaAsset:
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

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

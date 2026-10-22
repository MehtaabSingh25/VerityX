import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AnalysisJob, MediaAsset
from app.services.media_analysis import (
    compute_difference_hash,
    extract_image_metadata,
)


def compute_integrity_result(
    file_path: Path, expected_sha256: str
) -> dict[str, Any]:
    """Hash a stored file in chunks and compare it with its recorded digest."""
    digest = hashlib.sha256()
    with file_path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)

    actual_sha256 = digest.hexdigest()
    return {
        "check": "sha256_integrity",
        "expected_sha256": expected_sha256,
        "actual_sha256": actual_sha256,
        "matches": actual_sha256 == expected_sha256,
    }


def _media_path(storage_key: str) -> Path:
    """Resolve a storage key while preventing path traversal outside storage."""
    storage_root = Path(settings.media_storage_dir).resolve()
    candidate = (storage_root / storage_key).resolve()
    try:
        candidate.relative_to(storage_root)
    except ValueError as exc:
        raise ValueError("Invalid media storage key") from exc
    return candidate


def _mark_failed(job_id: UUID, message: str) -> None:
    with SessionLocal() as db:
        job = db.get(AnalysisJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = message[:2000]
        db.commit()


@celery_app.task(
    bind=True,
    name="verityx.run_analysis_job",
    max_retries=3,
    default_retry_delay=5,
)
def run_analysis_job(self: Task, job_id: str) -> dict[str, Any]:
    """Run a persisted analysis job and update its database lifecycle state."""
    try:
        parsed_job_id = UUID(job_id)
    except ValueError as exc:
        raise ValueError("Invalid analysis job ID") from exc

    with SessionLocal() as db:
        job = db.get(AnalysisJob, parsed_job_id)
        if job is None:
            raise ValueError("Analysis job not found")

        # Make repeated delivery safe for already completed jobs.
        if job.status == "completed" and job.result is not None:
            return job.result

        media = db.get(MediaAsset, job.media_asset_id)
        if media is None:
            job.status = "failed"
            job.error_message = "Media asset not found"
            db.commit()
            return {"status": "failed", "error": "Media asset not found"}

        job.status = "running"
        job.error_message = None
        db.commit()

        try:
            path = _media_path(media.storage_key or "")
            if job.analysis_type == "integrity_check":
                result = compute_integrity_result(path, media.sha256)
            elif job.analysis_type == "metadata_extract":
                if not media.mime_type.startswith("image/"):
                    raise ValueError(
                        "metadata_extract currently supports image files only"
                    )
                result = extract_image_metadata(path)
            elif job.analysis_type == "perceptual_hash":
                if not media.mime_type.startswith("image/"):
                    raise ValueError(
                        "perceptual_hash currently supports image files only"
                    )
                result = compute_difference_hash(path)
            else:
                raise ValueError(f"Unsupported analysis type: {job.analysis_type}")
            job.result = result
            job.status = "completed"
            job.error_message = None
            db.commit()
            return result

        except (OSError, SQLAlchemyError) as exc:
            db.rollback()
            # Retry transient file/DB errors; persist a terminal state after retries.
            if self.request.retries < self.max_retries:
                with SessionLocal() as retry_db:
                    retry_job = retry_db.get(AnalysisJob, parsed_job_id)
                    if retry_job is not None:
                        retry_job.status = "queued"
                        retry_job.error_message = str(exc)[:2000]
                        retry_db.commit()
                raise self.retry(exc=exc)

            _mark_failed(parsed_job_id, str(exc))
            raise

        except Exception as exc:
            db.rollback()
            _mark_failed(parsed_job_id, str(exc))
            raise

import hashlib
import logging
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AnalysisJob, AnalysisJobEvent, MediaAsset
from app.services.ai_detection import detect_ai_image
from app.services.media_analysis import (
    compute_difference_hash,
    extract_image_metadata,
)
from app.services.video_analysis import (
    extract_video_metadata,
    sample_video_frame_fingerprints,
)

logger = logging.getLogger("verityx.worker")


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
        db.add(AnalysisJobEvent(
            analysis_job_id=job.id,
            event_type="failed",
            status="failed",
            message="Analysis job failed.",
        ))
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

    task_started = time.perf_counter()
    with SessionLocal() as db:
        job = db.get(AnalysisJob, parsed_job_id)
        if job is None:
            raise ValueError("Analysis job not found")

        # Make repeated delivery safe for already completed jobs.
        if job.status == "completed" and job.result is not None:
            logger.info(
                "analysis_job_duplicate_delivery_skipped",
                extra={
                    "event": "analysis_job_duplicate_delivery_skipped",
                    "job_id": str(job.id),
                    "analysis_type": job.analysis_type,
                    "status": "completed",
                },
            )
            return job.result

        media = db.get(MediaAsset, job.media_asset_id)
        if media is None:
            job.status = "failed"
            job.error_message = "Media asset not found"
            db.add(AnalysisJobEvent(
                analysis_job_id=job.id,
                event_type="failed",
                status="failed",
                message="The media asset no longer exists.",
            ))
            db.commit()
            return {"status": "failed", "error": "Media asset not found"}

        job.status = "running"
        job.error_message = None
        logger.info(
            "analysis_job_started",
            extra={
                "event": "analysis_job_started",
                "job_id": str(job.id),
                "analysis_type": job.analysis_type,
                "status": "running",
            },
        )
        db.add(AnalysisJobEvent(
            analysis_job_id=job.id,
            event_type="started",
            status="running",
            message="Worker started processing the analysis job.",
        ))
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
            elif job.analysis_type == "ai_image_detection":
                if not media.mime_type.startswith("image/"):
                    raise ValueError("ai_image_detection currently supports image files only")
                result = detect_ai_image(path)
            elif job.analysis_type == "video_metadata":
                if not media.mime_type.startswith("video/"):
                    raise ValueError("video_metadata currently supports video files only")
                result = extract_video_metadata(path)
            elif job.analysis_type == "video_frame_fingerprints":
                if not media.mime_type.startswith("video/"):
                    raise ValueError(
                        "video_frame_fingerprints currently supports video files only"
                    )
                result = sample_video_frame_fingerprints(path)
            else:
                raise ValueError(f"Unsupported analysis type: {job.analysis_type}")
            job.result = result
            job.status = "completed"
            job.error_message = None
            db.add(AnalysisJobEvent(
                analysis_job_id=job.id,
                event_type="completed",
                status="completed",
                message="Analysis completed successfully.",
            ))
            db.commit()
            logger.info(
                "analysis_job_completed",
                extra={
                    "event": "analysis_job_completed",
                    "job_id": str(job.id),
                    "analysis_type": job.analysis_type,
                    "status": "completed",
                    "duration_ms": round((time.perf_counter() - task_started) * 1000, 2),
                },
            )
            return result

        except (OSError, SQLAlchemyError) as exc:
            db.rollback()
            # Retry transient file/DB errors; persist a terminal state after retries.
            if self.request.retries < self.max_retries:
                logger.warning(
                    "analysis_job_retry_scheduled",
                    extra={
                        "event": "analysis_job_retry_scheduled",
                        "job_id": str(parsed_job_id),
                        "analysis_type": job.analysis_type,
                        "retry_number": self.request.retries + 1,
                        "error_type": type(exc).__name__,
                    },
                )
                with SessionLocal() as retry_db:
                    retry_job = retry_db.get(AnalysisJob, parsed_job_id)
                    if retry_job is not None:
                        retry_job.status = "queued"
                        retry_job.error_message = str(exc)[:2000]
                        retry_db.add(AnalysisJobEvent(
                            analysis_job_id=retry_job.id,
                            event_type="retry_scheduled",
                            status="queued",
                            message="A transient error occurred; the job will be retried.",
                        ))
                        retry_db.commit()
                raise self.retry(exc=exc)

            _mark_failed(parsed_job_id, str(exc))
            logger.exception(
                "analysis_job_failed",
                extra={
                    "event": "analysis_job_failed",
                    "job_id": str(parsed_job_id),
                    "analysis_type": job.analysis_type,
                    "status": "failed",
                    "duration_ms": round((time.perf_counter() - task_started) * 1000, 2),
                    "error_type": type(exc).__name__,
                },
            )
            raise

        except Exception as exc:
            db.rollback()
            _mark_failed(parsed_job_id, str(exc))
            logger.exception(
                "analysis_job_failed",
                extra={
                    "event": "analysis_job_failed",
                    "job_id": str(parsed_job_id),
                    "analysis_type": job.analysis_type,
                    "status": "failed",
                    "duration_ms": round((time.perf_counter() - task_started) * 1000, 2),
                    "error_type": type(exc).__name__,
                },
            )
            raise

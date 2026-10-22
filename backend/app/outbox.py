"""Transactional outbox publishing for durable Celery task handoff."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import OutboxMessage
from app.tasks.analysis import run_analysis_job

logger = logging.getLogger("verityx.outbox")
LEASE_SECONDS = 60
MAX_BACKOFF_SECONDS = 300


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize SQLite's naive DateTime values and PostgreSQL aware values."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def publish_outbox_message(message_id: int, db: Session) -> bool:
    """Publish one message; retain it for retry if the broker is unavailable.

    The message is claimed in the database before publishing. A stale claim is
    recoverable after LEASE_SECONDS. The outbox provides at-least-once delivery;
    consumers must remain idempotent because a crash after broker publish but
    before recording ``published`` can cause redelivery.
    """
    message = db.get(OutboxMessage, message_id)
    if message is None or message.status == "published":
        return message is not None

    now = _utcnow()
    next_attempt_at = _as_utc(message.next_attempt_at)
    claimed_at = _as_utc(message.claimed_at)
    if message.status == "pending" and next_attempt_at is not None and next_attempt_at > now:
        return False
    if (
        message.status == "publishing"
        and claimed_at is not None
        and claimed_at > now - timedelta(seconds=LEASE_SECONDS)
    ):
        return False

    message.status = "publishing"
    message.claimed_at = now
    message.attempts += 1
    attempt_number = message.attempts
    db.commit()

    try:
        if message.task_name != "verityx.run_analysis_job":
            raise ValueError(f"Unsupported outbox task: {message.task_name}")
        job_id = str(message.payload["job_id"])
        run_analysis_job.delay(job_id)
    except Exception as exc:
        db.refresh(message)
        delay = min(MAX_BACKOFF_SECONDS, 2 ** min(attempt_number, 8))
        message.status = "pending"
        message.claimed_at = None
        message.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        message.next_attempt_at = _utcnow() + timedelta(seconds=delay)
        db.commit()
        logger.warning(
            "outbox_publish_failed",
            extra={
                "event": "outbox_publish_failed",
                "outbox_message_id": message_id,
                "analysis_job_id": str(message.analysis_job_id),
                "attempt": attempt_number,
                "retry_delay_seconds": delay,
                "error_type": type(exc).__name__,
            },
        )
        return False

    db.refresh(message)
    message.status = "published"
    message.published_at = _utcnow()
    message.claimed_at = None
    message.last_error = None
    db.commit()
    logger.info(
        "outbox_message_published",
        extra={
            "event": "outbox_message_published",
            "outbox_message_id": message_id,
            "analysis_job_id": str(message.analysis_job_id),
            "attempt": attempt_number,
        },
    )
    return True


def dispatch_one_pending_message(session_factory: Any = SessionLocal) -> bool:
    """Find and publish one due message, including claims abandoned by a crash."""
    now = _utcnow()
    stale_claim = now - timedelta(seconds=LEASE_SECONDS)
    with session_factory() as db:
        message = db.scalar(
            select(OutboxMessage)
            .where(
                or_(
                    (OutboxMessage.status == "pending")
                    & (OutboxMessage.next_attempt_at <= now),
                    (OutboxMessage.status == "publishing")
                    & (OutboxMessage.claimed_at <= stale_claim),
                )
            )
            .order_by(OutboxMessage.created_at, OutboxMessage.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if message is None:
            return False
        # Publish using the same session so the row lock is held until the
        # message transitions to ``publishing`` and that claim is committed.
        return publish_outbox_message(message.id, db)


def run_dispatch_loop(poll_interval_seconds: float = 2.0) -> None:
    """Continuously drain the outbox; intended for a dedicated Compose service."""
    logger.info(
        "outbox_dispatcher_started",
        extra={"event": "outbox_dispatcher_started", "poll_interval_seconds": poll_interval_seconds},
    )
    while True:
        try:
            dispatched = dispatch_one_pending_message()
        except Exception:
            logger.exception("outbox_dispatcher_iteration_failed", extra={"event": "outbox_dispatcher_iteration_failed"})
            dispatched = False
        if not dispatched:
            time.sleep(poll_interval_seconds)

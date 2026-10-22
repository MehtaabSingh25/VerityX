from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "verityx",
    broker=settings.redis_url,
    include=["app.tasks.analysis"],
)

celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    task_ignore_result=True,
)

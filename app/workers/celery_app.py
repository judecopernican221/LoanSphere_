"""
Celery application configuration.
Redis is used as both the broker (receives tasks) and backend (stores results).
"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "loan_processor",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Reliability: task is NOT acknowledged until it completes
    # If a worker dies mid-task, the task is re-queued automatically
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Result expiry: keep results for 1 hour
    result_expires=3600,

    # Retry settings
    task_max_retries=3,
    task_default_retry_delay=60,  # 60 seconds between retries

    # Worker
    worker_prefetch_multiplier=1,  # process one task at a time per worker
)

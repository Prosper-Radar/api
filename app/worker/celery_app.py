"""
Celery application — broker = Redis (optional).

If Redis is not running (CELERY_BROKER_URL not set or unreachable) the app
degrades gracefully: all tasks execute synchronously via `task.apply()`.
"""
import logging
import os

logger = logging.getLogger(__name__)

_broker = os.getenv("CELERY_BROKER_URL", "")

try:
    from celery import Celery

    if _broker:
        celery_app = Celery(
            "dealscout",
            broker=_broker,
            backend=os.getenv("CELERY_RESULT_BACKEND", _broker),
            include=["app.worker.tasks"],
        )
        celery_app.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            timezone="America/New_York",
            task_track_started=True,
            worker_prefetch_multiplier=1,  # one task at a time per worker
        )
        logger.info("Celery configured with broker: %s", _broker)
    else:
        celery_app = None
        logger.info("CELERY_BROKER_URL not set — Celery disabled, tasks run inline")
except Exception as exc:  # pragma: no cover
    celery_app = None
    logger.warning("Failed to init Celery (%s) — tasks run inline", exc)


def dispatch(task_fn, *args, **kwargs):
    """
    Fire-and-forget helper.

    Uses Celery delay() when the broker is available, otherwise runs
    the coroutine synchronously (via asyncio.run) so development works
    without Redis.
    """
    if celery_app is not None:
        return task_fn.delay(*args, **kwargs)

    import asyncio, inspect
    result = task_fn(*args, **kwargs)
    if inspect.iscoroutine(result):
        asyncio.create_task(result)
    return result

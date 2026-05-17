"""
Celery tasks — wraps async scoring & scraping in synchronous Celery-compatible wrappers.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


def _run(coro):
    """Run a coroutine from a synchronous Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ─── Import Celery app lazily so module loads even without broker ──────────────
def _get_celery():
    from app.worker.celery_app import celery_app
    return celery_app


# Only register tasks when Celery is available
_celery = _get_celery()

if _celery is not None:
    @_celery.task(name="tasks.sync_county", bind=True, max_retries=3, default_retry_delay=60)
    def sync_county(self, county: str):
        """Fetch parcels from county scraper and upsert into DB."""
        from app.db.session import async_session
        from app.scrapers import miami_dade, hillsborough

        async def _do():
            async with async_session() as db:
                if county == "miami-dade":
                    raw = await miami_dade.fetch_parcels(limit=500)
                    normalize = miami_dade.normalize_parcel
                elif county == "hillsborough":
                    raw = await hillsborough.fetch_parcels(limit=500)
                    normalize = hillsborough.normalize_parcel
                else:
                    logger.warning("Unknown county: %s", county)
                    return

                from app.tasks.sync import upsert_parcels
                await upsert_parcels(db, [normalize(r) for r in raw if r])

        try:
            _run(_do())
        except Exception as exc:
            raise self.retry(exc=exc)

    @_celery.task(name="tasks.score_parcel", bind=True, max_retries=2, default_retry_delay=30)
    def score_parcel(self, parcel_id: str):
        """(Re)score a single parcel — used after a new scrape lands."""
        from app.db.session import async_session

        async def _do():
            async with async_session() as db:
                from app.tasks.scoring import score_one_parcel
                await score_one_parcel(db, parcel_id)

        try:
            _run(_do())
        except Exception as exc:
            raise self.retry(exc=exc)
else:
    # Stub task objects so callers can call .delay() without crashing
    class _Stub:
        def delay(self, *a, **kw):
            logger.debug("Celery disabled — skipping background task")

    sync_county = _Stub()
    score_parcel = _Stub()

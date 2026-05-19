import logging

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.logging import configure_logging
from app.api.v1.router import api_router
from app.db.session import AsyncSessionLocal
from app.scoring.version import MODEL_VERSION

configure_logging()

settings = get_settings()
logger = logging.getLogger(__name__)

# ── Sentry ───────────────────────────────────────────────────────────────────
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        environment=settings.environment,
        release=f"dealscout-api@{MODEL_VERSION}",
    )
    logger.info("Sentry initialized (env=%s)", settings.environment)

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=MODEL_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


# ── Health check enrichi ─────────────────────────────────────────────────────
@app.get("/health")
async def health():
    checks: dict[str, bool | int] = {
        "db": False,
        "water_bodies": False,
        "deal_scores": False,
        "redis": False,
    }

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
            checks["db"] = True

            result = await db.execute(text("SELECT COUNT(*) FROM water_bodies"))
            checks["water_bodies"] = (result.scalar() or 0) > 0

            result = await db.execute(
                text("SELECT COUNT(*) FROM deal_scores WHERE total_score > 0")
            )
            checks["deal_scores"] = result.scalar() or 0
    except Exception as exc:
        logger.error("Health check DB error: %s", exc)

    try:
        from app.worker.celery_app import celery_app
        if celery_app is not None:
            celery_app.control.ping(timeout=1)
            checks["redis"] = True
    except Exception:
        pass

    return {
        "status": "ok" if checks["db"] else "degraded",
        "version": MODEL_VERSION,
        "checks": checks,
    }

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.config import get_settings

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/miami-dade")
async def sync_miami_dade(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger Miami-Dade Property Appraiser data refresh."""
    from app.tasks.sync import run_miami_dade_sync
    background_tasks.add_task(run_miami_dade_sync, db)
    return {"status": "started", "source": "miami-dade"}


@router.post("/hillsborough")
async def sync_hillsborough(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger Hillsborough County data refresh."""
    from app.tasks.sync import run_hillsborough_sync
    background_tasks.add_task(run_hillsborough_sync, db)
    return {"status": "started", "source": "hillsborough"}


@router.post("/scores")
async def recompute_scores(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Recompute all deal scores."""
    from app.tasks.scoring import run_score_computation
    background_tasks.add_task(run_score_computation, db)
    return {"status": "started", "task": "score-computation"}

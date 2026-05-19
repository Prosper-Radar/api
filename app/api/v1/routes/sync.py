from fastapi import APIRouter, BackgroundTasks

from app.core.config import get_settings

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/miami-dade")
async def sync_miami_dade(
    background_tasks: BackgroundTasks,
):
    """Trigger Miami-Dade Property Appraiser data refresh."""
    from app.tasks.sync import run_miami_dade_sync
    background_tasks.add_task(run_miami_dade_sync)
    return {"status": "started", "source": "miami-dade"}


@router.post("/hillsborough")
async def sync_hillsborough(
    background_tasks: BackgroundTasks,
):
    """Trigger Hillsborough County data refresh."""
    from app.tasks.sync import run_hillsborough_sync
    background_tasks.add_task(run_hillsborough_sync)
    return {"status": "started", "source": "hillsborough"}


@router.post("/scores")
async def recompute_scores(
    background_tasks: BackgroundTasks,
):
    """Recompute all deal scores."""
    from app.tasks.scoring import run_score_computation
    background_tasks.add_task(run_score_computation)
    return {"status": "started", "task": "score-computation"}

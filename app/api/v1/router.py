from fastapi import APIRouter

from app.api.v1.routes.deals import router as deals_router
from app.api.v1.routes.sync import router as sync_router
from app.api.v1.routes.assembly import router as assembly_router
from app.api.v1.routes.memo import router as memo_router

api_router = APIRouter()
api_router.include_router(deals_router)
api_router.include_router(sync_router)
api_router.include_router(assembly_router)
api_router.include_router(memo_router)

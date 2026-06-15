from fastapi import APIRouter

from app.api.v1.endpoints import health, home
from app.gatekeeper.apikeys_api import router as apikeys_router

api_router = APIRouter()
api_router.include_router(home.router, tags=["home"])
api_router.include_router(health.router, tags=["health"])
api_router.include_router(apikeys_router)

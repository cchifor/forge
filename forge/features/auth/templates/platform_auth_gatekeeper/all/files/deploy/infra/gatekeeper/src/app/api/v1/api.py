from fastapi import APIRouter

from app.api.v1.endpoints import health, home

api_router = APIRouter()
api_router.include_router(home.router, tags=["home"])
api_router.include_router(health.router, tags=["health"])

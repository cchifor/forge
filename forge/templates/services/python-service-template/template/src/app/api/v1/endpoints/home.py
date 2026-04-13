from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter

from app.core.config import Settings

router = APIRouter()


@router.get("/")
async def root():
    return {"status": "running"}


@router.get("/info")
@inject
async def info(settings: FromDishka[Settings]):
    return {
        "title": settings.app.title,
        "version": settings.app.version,
        "description": settings.app.description,
    }

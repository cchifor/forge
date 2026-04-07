import logging

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/", operation_id="index")
async def index():
    return {"message": "Gatekeeper is running"}


@router.get("/info", operation_id="info", response_model=dict)
async def info():
    return settings.app.model_dump()

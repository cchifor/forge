"""REST endpoints for background task management.

Routes
------
POST   /tasks            -- Enqueue a new background task
GET    /tasks/{id}       -- Get task status
DELETE /tasks/{id}       -- Cancel a pending task
"""

from __future__ import annotations

from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from service.security.auth import oauth2_scheme
from service.tasks.registry import registered_types
from service.tasks.service import TaskService

router = APIRouter(route_class=DishkaRoute, dependencies=[Depends(oauth2_scheme)])


class TaskEnqueueRequest(BaseModel):
    task_type: str = Field(..., description="Registered task type name")
    payload: dict | None = Field(None, description="Task payload")
    max_retries: int = Field(3, ge=0, le=10)


class TaskEnqueueResponse(BaseModel):
    id: str
    task_type: str
    status: str


class TaskStatusResponse(BaseModel):
    id: str
    task_type: str
    status: str
    payload: dict | None = None
    result: dict | None = None
    error: str | None = None
    attempts: int
    max_retries: int
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


@router.post(
    "",
    response_model=TaskEnqueueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enqueue a background task",
)
async def enqueue_task(
    service: FromDishka[TaskService],
    data: TaskEnqueueRequest,
) -> TaskEnqueueResponse:
    known = registered_types()
    if data.task_type not in known:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown task_type '{data.task_type}'. Registered: {known}",
        )

    task_id = await service.enqueue(
        data.task_type, payload=data.payload, max_retries=data.max_retries
    )
    return TaskEnqueueResponse(id=str(task_id), task_type=data.task_type, status="PENDING")


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    summary="Get task status",
)
async def get_task(
    task_id: UUID,
    service: FromDishka[TaskService],
) -> TaskStatusResponse:
    task = await service.get(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskStatusResponse(
        id=str(task.id),
        task_type=task.task_type,
        status=task.status,
        payload=task.payload,
        result=task.result,
        error=task.error,
        attempts=task.attempts,
        max_retries=task.max_retries,
        created_at=str(task.created_at) if task.created_at else None,
        started_at=str(task.started_at) if task.started_at else None,
        completed_at=str(task.completed_at) if task.completed_at else None,
    )


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a pending task",
)
async def cancel_task(
    task_id: UUID,
    service: FromDishka[TaskService],
) -> None:
    cancelled = await service.cancel(task_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task cannot be cancelled (not PENDING or not found)",
        )

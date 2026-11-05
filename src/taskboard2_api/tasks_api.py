"""HTTP routes for creating and listing tasks."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .task_schemas import TaskCreate, TaskOut
from .task_store import TaskStore

router = APIRouter()


def get_task_store(request: Request) -> TaskStore:
    store: TaskStore = request.app.state.task_store
    return store


@router.post("/tasks", status_code=201, response_model=TaskOut)
def create_task(body: TaskCreate, request: Request) -> TaskOut:
    """Create a task."""
    task = get_task_store(request).add(body.title, body.due_date)
    return TaskOut.model_validate(task)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(request: Request) -> list[TaskOut]:
    """List all tasks, oldest first."""
    return [TaskOut.model_validate(t) for t in get_task_store(request).list_all()]

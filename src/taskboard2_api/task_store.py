"""In-memory task storage behind a small interface."""

from __future__ import annotations

import datetime
import threading
import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    title: str
    due_date: datetime.date | None


class TaskStore(Protocol):
    def add(self, title: str, due_date: datetime.date | None) -> Task: ...

    def list_all(self) -> list[Task]:
        """Return a copy of all tasks, oldest first."""
        ...


class InMemoryTaskStore:
    """Process-local store keeping tasks in creation order."""

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._lock = threading.Lock()

    def add(self, title: str, due_date: datetime.date | None) -> Task:
        task = Task(id=str(uuid.uuid4()), title=title, due_date=due_date)
        with self._lock:
            self._tasks.append(task)
        return task

    def list_all(self) -> list[Task]:
        with self._lock:
            return list(self._tasks)

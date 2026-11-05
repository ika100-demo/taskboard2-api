"""Task storage on PostgreSQL with a lazily created schema."""

from __future__ import annotations

import datetime
import threading
import uuid
from typing import Final

import psycopg
from psycopg_pool import NullConnectionPool

from taskboard2_api.task_store import Task, TaskStoreUnavailable

SCHEMA_LOCK_KEY: Final = 7_202_002_001

_CREATE_TABLE: Final = """
CREATE TABLE IF NOT EXISTS tasks (
  seq      BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,  -- creation order
  id       UUID PRIMARY KEY,
  title    VARCHAR(200) NOT NULL,
  due_date DATE NULL
)
"""


class PostgresTaskStore:
    """TaskStore backed by PostgreSQL; never connects at construction."""

    def __init__(self, conninfo: str) -> None:
        self._pool: NullConnectionPool = NullConnectionPool(
            conninfo,
            max_size=10,
            timeout=2.0,
            open=True,
            name="taskboard2-api-tasks",
            kwargs={
                "connect_timeout": 2,
                "options": "-c statement_timeout=3000",
                "application_name": "taskboard2-api",
            },
        )
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _ensure_schema(self, conn: psycopg.Connection) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_KEY,))
                conn.execute(_CREATE_TABLE.encode())
            self._schema_ready = True

    def add(self, title: str, due_date: datetime.date | None) -> Task:
        task_id = uuid.uuid4()
        try:
            with self._pool.connection() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    "INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)",
                    (task_id, title, due_date),
                )
        except psycopg.Error as exc:
            raise TaskStoreUnavailable() from exc
        return Task(id=str(task_id), title=title, due_date=due_date)

    def list_all(self) -> list[Task]:
        try:
            with self._pool.connection() as conn:
                self._ensure_schema(conn)
                rows = conn.execute("SELECT id, title, due_date FROM tasks ORDER BY seq").fetchall()
        except psycopg.Error as exc:
            raise TaskStoreUnavailable() from exc
        return [Task(str(r[0]), r[1], r[2]) for r in rows]

    def close(self) -> None:
        try:
            self._pool.close()
        except psycopg.Error:
            pass

"""Acceptance tests for spec 002 (persist tasks in Postgres behind the unchanged API).

Runs in-process against a real Postgres started with testcontainers. AC-002.10 is the
smoke criterion, checked by tests/test_smoke_tasks.py.
"""

from __future__ import annotations

import contextlib
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

UNAVAILABLE = {"detail": "Task store unavailable"}
DEAD_URL = "postgresql://u:p@127.0.0.1:1/x"


@pytest.fixture(scope="session")
def pg_container() -> Iterator[Any]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        yield container


@pytest.fixture()
def db_url(pg_container: Any) -> str:
    """URL of a fresh, empty database inside the shared container."""
    import psycopg

    admin_url = pg_container.get_connection_url()
    name = f"t_{uuid.uuid4().hex}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_url.rpartition("/")
    return f"{base}/{name}"


@pytest.fixture()
def make_client(monkeypatch: pytest.MonkeyPatch):
    def _make(url: str) -> TestClient:
        from taskboard2_api.main import create_app

        monkeypatch.setenv("DATABASE_URL", url)
        return TestClient(create_app())

    return _make


@contextlib.contextmanager
def db_paused(container: Any) -> Iterator[None]:
    wrapped = container.get_wrapped_container()
    wrapped.pause()
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            wrapped.unpause()


def assert_unavailable(response) -> None:
    assert response.status_code == 503
    assert response.headers["content-type"].split(";")[0] == "application/json"
    assert response.json() == UNAVAILABLE


def timed(call, *args, **kwargs):
    start = time.monotonic()
    response = call(*args, **kwargs)
    assert time.monotonic() - start < 5
    return response


def assert_field_error(response, field: str) -> None:
    assert response.status_code == 422
    assert any(entry["loc"][-1] == field for entry in response.json()["detail"])


def test_tasks_survive_restart(db_url: str, make_client) -> None:  # AC-002.1
    first = make_client(db_url)
    created = [first.post("/tasks", json={"title": t}).json() for t in ("A", "B", "C")]
    second = make_client(db_url)
    response = second.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created


def test_new_task_after_restart_has_new_id(db_url: str, make_client) -> None:  # AC-002.2
    first = make_client(db_url)
    old = [first.post("/tasks", json={"title": t}).json() for t in ("A", "B")]
    second = make_client(db_url)
    response = second.post("/tasks", json={"title": "D"})
    assert response.status_code == 201
    new = response.json()
    assert new["id"] not in {t["id"] for t in old}
    assert second.get("/tasks").json() == [*old, new]


def test_two_instances_share_tasks(db_url: str, make_client) -> None:  # AC-002.3
    one = make_client(db_url)
    two = make_client(db_url)
    a = one.post("/tasks", json={"title": "On one"}).json()
    assert two.get("/tasks").json() == [a]
    b = two.post("/tasks", json={"title": "On two"}).json()
    assert one.get("/tasks").json() == [a, b]
    assert two.get("/tasks").json() == [a, b]


def test_simultaneous_start_on_fresh_database(db_url: str, make_client) -> None:  # AC-002.4
    barrier = threading.Barrier(2)
    clients: list[TestClient | None] = [None, None]
    results: dict[int, list[int]] = {}
    errors: list[BaseException] = []

    def run(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            client = make_client(db_url)
            clients[index] = client
            results[index] = [
                client.get("/tasks").status_code,
                client.post("/tasks", json={"title": "Buy milk"}).status_code,
            ]
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    assert results == {0: [200, 201], 1: [200, 201]}
    for client in clients:
        assert client is not None
        listed = client.get("/tasks")
        assert listed.status_code == 200
        assert [t["title"] for t in listed.json()] == ["Buy milk", "Buy milk"]


def test_fresh_database_lists_empty(db_url: str, make_client) -> None:  # AC-002.5
    response = make_client(db_url).get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_unreachable_database_answers_503(make_client) -> None:  # AC-002.6
    client = make_client(DEAD_URL)
    assert_unavailable(timed(client.get, "/tasks"))
    assert_unavailable(timed(client.post, "/tasks", json={"title": "Lost task"}))


def test_paused_database_answers_503_and_stores_nothing(  # AC-002.6
    pg_container: Any, db_url: str, make_client
) -> None:
    client = make_client(db_url)
    assert client.get("/tasks").status_code == 200
    with db_paused(pg_container):
        assert_unavailable(timed(client.get, "/tasks"))
        assert_unavailable(timed(client.post, "/tasks", json={"title": "Lost task"}))
    listed = make_client(db_url).get("/tasks")
    assert listed.status_code == 200
    assert all(t["title"] != "Lost task" for t in listed.json())


def test_service_recovers_without_restart(pg_container: Any, db_url: str, make_client) -> None:
    # AC-002.7
    client = make_client(db_url)
    assert client.get("/tasks").status_code == 200
    with db_paused(pg_container):
        assert_unavailable(timed(client.get, "/tasks"))
    created = client.post("/tasks", json={"title": "Back again"})
    assert created.status_code == 201
    listed = client.get("/tasks")
    assert listed.status_code == 200
    assert created.json() in listed.json()


def test_invalid_body_is_422_when_database_down(make_client) -> None:  # AC-002.8
    client = make_client(DEAD_URL)
    assert_field_error(timed(client.post, "/tasks", json={"title": ""}), "title")
    bad_due = {"title": "Buy milk", "due_date": "tomorrow"}
    assert_field_error(timed(client.post, "/tasks", json=bad_due), "due_date")


def test_starts_with_database_down_then_recovers(  # AC-002.9
    pg_container: Any, db_url: str, make_client
) -> None:
    with db_paused(pg_container):
        client = timed(make_client, db_url)
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert_unavailable(timed(client.get, "/tasks"))
    assert client.get("/tasks").status_code == 200
    assert client.post("/tasks", json={"title": "Buy milk"}).status_code == 201


# AC-002.10 (smoke) is checked by tests/test_smoke_tasks.py against the public URL.


def test_fresh_db_lists_empty(db_url: str, make_client) -> None:  # AC-002.11 (AC-001.4)
    response = make_client(db_url).get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_fresh_db_creation_order(db_url: str, make_client) -> None:  # AC-002.11 (AC-001.5)
    client = make_client(db_url)
    ids = [client.post("/tasks", json={"title": t}).json()["id"] for t in ("A", "B", "C")]
    assert [t["id"] for t in client.get("/tasks").json()] == ids


def test_fresh_db_duplicate_titles(db_url: str, make_client) -> None:  # AC-002.11 (AC-001.6)
    client = make_client(db_url)
    first = client.post("/tasks", json={"title": "Buy milk"}).json()
    second = client.post("/tasks", json={"title": "Buy milk"}).json()
    assert first["id"] != second["id"]
    assert client.get("/tasks").json() == [first, second]


def test_fresh_db_title_length_limit(db_url: str, make_client) -> None:  # AC-002.11 (AC-001.8)
    client = make_client(db_url)
    assert_field_error(client.post("/tasks", json={"title": "x" * 201}), "title")
    assert client.get("/tasks").json() == []
    for title in ("x" * 200, f"  {'x' * 200}  "):
        response = client.post("/tasks", json={"title": title})
        assert response.status_code == 201
        assert response.json()["title"] == "x" * 200


def test_fresh_db_title_trimmed(db_url: str, make_client) -> None:  # AC-002.11 (AC-001.9)
    client = make_client(db_url)
    response = client.post("/tasks", json={"title": "  Buy milk  "})
    assert response.status_code == 201
    assert response.json()["title"] == "Buy milk"
    assert client.get("/tasks").json()[0]["title"] == "Buy milk"


def test_fresh_db_past_due_date_accepted(db_url: str, make_client) -> None:  # AC-002.11 (AC-001.11)
    client = make_client(db_url)
    response = client.post("/tasks", json={"title": "Old task", "due_date": "2026-01-01"})
    assert response.status_code == 201
    assert response.json()["due_date"] == "2026-01-01"

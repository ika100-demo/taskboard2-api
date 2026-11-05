"""Acceptance tests for spec 001 (create and list in-memory tasks)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def make_client() -> TestClient:
    from taskboard2_api.main import create_app

    return TestClient(create_app())


@pytest.fixture()
def tc() -> TestClient:
    return make_client()


def assert_field_error(response, field: str) -> None:
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(entry["loc"][-1] == field for entry in detail)


def test_create_task_title_only(tc: TestClient) -> None:  # AC-001.1
    response = tc.post("/tasks", json={"title": "Buy milk"})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "title", "due_date"}
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] is None


def test_create_task_with_due_date(tc: TestClient) -> None:  # AC-001.2
    response = tc.post("/tasks", json={"title": "File taxes", "due_date": "2026-12-01"})
    assert response.status_code == 201
    assert response.json()["title"] == "File taxes"
    assert response.json()["due_date"] == "2026-12-01"


def test_created_task_is_listed(tc: TestClient) -> None:  # AC-001.3
    created = tc.post("/tasks", json={"title": "Buy milk"}).json()
    response = tc.get("/tasks")
    assert response.status_code == 200
    matches = [t for t in response.json() if t["id"] == created["id"]]
    assert matches == [created]


def test_fresh_service_lists_empty(tc: TestClient) -> None:  # AC-001.4
    response = tc.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_list_is_in_creation_order(tc: TestClient) -> None:  # AC-001.5
    ids = [tc.post("/tasks", json={"title": t}).json()["id"] for t in ("A", "B", "C")]
    assert [t["id"] for t in tc.get("/tasks").json()] == ids


def test_same_title_gets_distinct_ids(tc: TestClient) -> None:  # AC-001.6
    tc.post("/tasks", json={"title": "Buy milk"})
    tc.post("/tasks", json={"title": "Buy milk"})
    tasks = tc.get("/tasks").json()
    assert len(tasks) == 2
    assert [t["title"] for t in tasks] == ["Buy milk", "Buy milk"]
    assert tasks[0]["id"] != tasks[1]["id"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": 123},
        {"title": True},
        {"title": None},
        {"title": ""},
        {"title": "   "},
    ],
)
def test_invalid_title_rejected(tc: TestClient, body: dict) -> None:  # AC-001.7
    before = len(tc.get("/tasks").json())
    assert_field_error(tc.post("/tasks", json=body), "title")
    assert len(tc.get("/tasks").json()) <= before


def test_title_length_limit(tc: TestClient) -> None:  # AC-001.8
    assert_field_error(tc.post("/tasks", json={"title": "x" * 201}), "title")
    assert_field_error(tc.post("/tasks", json={"title": " " + "x" * 201 + " "}), "title")
    assert tc.get("/tasks").json() == []
    title = "x" * 200
    for sent in (title, f"  {title}  "):
        response = tc.post("/tasks", json={"title": sent})
        assert response.status_code == 201
        assert response.json()["title"] == title


def test_title_is_trimmed(tc: TestClient) -> None:  # AC-001.9
    created = tc.post("/tasks", json={"title": "  Buy milk  "}).json()
    assert created["title"] == "Buy milk"
    assert tc.get("/tasks").json()[0]["title"] == "Buy milk"


@pytest.mark.parametrize("due", ["tomorrow", "2026-02-30", "2026-12-01T10:00:00Z", 20261201])
def test_invalid_due_date_rejected(tc: TestClient, due: object) -> None:  # AC-001.10
    before = len(tc.get("/tasks").json())
    response = tc.post("/tasks", json={"title": "Buy milk", "due_date": due})
    assert_field_error(response, "due_date")
    assert len(tc.get("/tasks").json()) <= before


def test_past_due_date_accepted(tc: TestClient) -> None:  # AC-001.11
    response = tc.post("/tasks", json={"title": "Old task", "due_date": "2026-01-01"})
    assert response.status_code == 201
    assert response.json()["due_date"] == "2026-01-01"


def test_restart_loses_tasks() -> None:  # AC-001.12
    first = make_client()
    first.post("/tasks", json={"title": "Buy milk"})
    assert len(first.get("/tasks").json()) == 1
    second = make_client()
    response = second.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []

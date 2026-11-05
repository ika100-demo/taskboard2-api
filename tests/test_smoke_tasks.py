"""Smoke tests for spec 001 (AC-001.1, .2, .3, .7, .10), reaching the service by URL only.

They are also the checks of AC-002.10: the same tests run against the Postgres-backed service.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

import pytest


def _call(base: str, method: str, path: str, body: object = None) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as err:
        return err.code, json.load(err)


@pytest.mark.smoke
def test_smoke_ac_001_1_create_task_title_only(smoke_base_url: str) -> None:  # AC-001.1, AC-002.10
    title = f"smoke-{uuid.uuid4()}"
    status, body = _call(smoke_base_url, "POST", "/tasks", {"title": title})
    assert status == 201
    assert set(body) == {"id", "title", "due_date"}
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == title
    assert body["due_date"] is None


@pytest.mark.smoke
def test_smoke_ac_001_2_create_task_with_due_date(
    smoke_base_url: str,
) -> None:  # AC-001.2, AC-002.10
    title = f"smoke-{uuid.uuid4()}"
    status, body = _call(
        smoke_base_url, "POST", "/tasks", {"title": title, "due_date": "2026-12-01"}
    )
    assert status == 201
    assert body["title"] == title
    assert body["due_date"] == "2026-12-01"


@pytest.mark.smoke
def test_smoke_ac_001_3_created_task_is_listed(smoke_base_url: str) -> None:  # AC-001.3, AC-002.10
    _, created = _call(smoke_base_url, "POST", "/tasks", {"title": f"smoke-{uuid.uuid4()}"})
    status, tasks = _call(smoke_base_url, "GET", "/tasks")
    assert status == 200
    assert [t for t in tasks if t["id"] == created["id"]] == [created]


@pytest.mark.smoke
def test_smoke_ac_001_7_invalid_title_rejected(smoke_base_url: str) -> None:  # AC-001.7, AC-002.10
    _, before = _call(smoke_base_url, "GET", "/tasks")
    bad = [{}, {"title": 123}, {"title": True}, {"title": None}, {"title": ""}, {"title": " "}]
    for body in bad:
        status, resp = _call(smoke_base_url, "POST", "/tasks", body)
        assert status == 422
        assert any(e["loc"][-1] == "title" for e in resp["detail"])
    _, after = _call(smoke_base_url, "GET", "/tasks")
    assert len(after) <= len(before)


@pytest.mark.smoke
def test_smoke_ac_001_10_invalid_due_date_rejected(
    smoke_base_url: str,
) -> None:  # AC-001.10, AC-002.10
    _, before = _call(smoke_base_url, "GET", "/tasks")
    for due in ("tomorrow", "2026-02-30", "2026-12-01T10:00:00Z", 20261201):
        status, resp = _call(
            smoke_base_url, "POST", "/tasks", {"title": f"smoke-{uuid.uuid4()}", "due_date": due}
        )
        assert status == 422
        assert any(e["loc"][-1] == "due_date" for e in resp["detail"])
    _, after = _call(smoke_base_url, "GET", "/tasks")
    assert len(after) <= len(before)

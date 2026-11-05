"""Unit tests for PostgresTaskStore against a real Postgres (testcontainers)."""

from __future__ import annotations

import datetime
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from taskboard2_api.postgres_task_store import PostgresTaskStore
from taskboard2_api.task_store import TaskStoreUnavailable


@pytest.fixture(scope="module")
def pg_container() -> Iterator[Any]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        yield container


@pytest.fixture()
def db_url(pg_container: Any) -> str:
    import psycopg

    admin_url = pg_container.get_connection_url()
    name = f"t_{uuid.uuid4().hex}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_url.rpartition("/")
    return f"{base}/{name}"


def test_empty_list_on_new_database(db_url: str) -> None:
    store = PostgresTaskStore(db_url)
    try:
        assert store.list_all() == []
    finally:
        store.close()


def test_order_kept_and_fields_roundtrip(db_url: str) -> None:
    store = PostgresTaskStore(db_url)
    try:
        created = [
            store.add("A", None),
            store.add("B", datetime.date(2030, 1, 2)),
            store.add("C", None),
        ]
        assert store.list_all() == created
        assert created[1].due_date == datetime.date(2030, 1, 2)
        assert len({t.id for t in created}) == 3
    finally:
        store.close()


def test_two_stores_see_each_other(db_url: str) -> None:
    one, two = PostgresTaskStore(db_url), PostgresTaskStore(db_url)
    try:
        a = one.add("A", None)
        b = two.add("B", None)
        assert one.list_all() == [a, b]
        assert two.list_all() == [a, b]
    finally:
        one.close()
        two.close()


def test_second_store_on_existing_table(db_url: str) -> None:
    one = PostgresTaskStore(db_url)
    a = one.add("A", None)
    one.close()
    two = PostgresTaskStore(db_url)
    try:
        assert two.list_all() == [a]
    finally:
        two.close()


def test_concurrent_first_calls(db_url: str) -> None:
    stores = [PostgresTaskStore(db_url), PostgresTaskStore(db_url)]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def work(store: PostgresTaskStore, title: str) -> None:
        try:
            barrier.wait()
            store.add(title, None)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(s, str(i))) for i, s in enumerate(stores)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert errors == []
        assert len(stores[0].list_all()) == 2
    finally:
        for s in stores:
            s.close()


def test_unreachable_raises_unavailable() -> None:
    store = PostgresTaskStore("postgresql://u:p@127.0.0.1:1/x")
    try:
        start = time.monotonic()
        with pytest.raises(TaskStoreUnavailable):
            store.list_all()
        with pytest.raises(TaskStoreUnavailable):
            store.add("A", None)
        assert time.monotonic() - start < 5
    finally:
        store.close()


def test_close_is_idempotent(db_url: str) -> None:
    store = PostgresTaskStore(db_url)
    store.close()
    store.close()
    with pytest.raises(TaskStoreUnavailable):
        store.list_all()

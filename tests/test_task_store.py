import datetime

from taskboard2_api.task_store import InMemoryTaskStore


def test_empty_on_creation() -> None:
    assert InMemoryTaskStore().list_all() == []


def test_order_preserved() -> None:
    store = InMemoryTaskStore()
    created = [store.add(t, None) for t in ("A", "B", "C")]
    assert store.list_all() == created
    assert [t.title for t in store.list_all()] == ["A", "B", "C"]


def test_distinct_ids_for_equal_titles() -> None:
    store = InMemoryTaskStore()
    a = store.add("Buy milk", None)
    b = store.add("Buy milk", datetime.date(2030, 1, 1))
    assert a.id != b.id
    assert b.due_date == datetime.date(2030, 1, 1)
    assert len(store.list_all()) == 2


def test_returned_list_is_a_copy() -> None:
    store = InMemoryTaskStore()
    store.add("A", None)
    snapshot = store.list_all()
    snapshot.clear()
    assert len(store.list_all()) == 1


def test_instances_do_not_share_state() -> None:
    first = InMemoryTaskStore()
    first.add("A", None)
    assert InMemoryTaskStore().list_all() == []

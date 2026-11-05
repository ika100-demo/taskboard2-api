import json

import pytest
from pydantic import ValidationError

from taskboard2_api.task_schemas import TaskCreate, TaskOut


def _fails_on(payload: dict, field: str) -> None:
    with pytest.raises(ValidationError) as exc:
        TaskCreate.model_validate_json(json.dumps(payload))
    assert any(e["loc"][-1] == field for e in exc.value.errors())


@pytest.mark.parametrize("bad", [123, True, None, "", "   "])
def test_bad_title_fails(bad):
    _fails_on({"title": bad}, "title")


def test_missing_title_fails():
    _fails_on({}, "title")


def test_title_length_limits():
    assert TaskCreate.model_validate_json(json.dumps({"title": "a" * 200})).title == "a" * 200
    padded = {"title": f"  {'a' * 200}  "}
    assert TaskCreate.model_validate_json(json.dumps(padded)).title == "a" * 200
    _fails_on({"title": "a" * 201}, "title")
    _fails_on({"title": f" {'a' * 201} "}, "title")


def test_title_is_trimmed():
    assert TaskCreate.model_validate({"title": "  Buy milk  "}).title == "Buy milk"


BAD_DATES = ["tomorrow", "2026-02-30", "2026-12-01T10:00:00Z", 20261201, "20261201"]


@pytest.mark.parametrize("bad", BAD_DATES)
def test_bad_due_date_fails(bad):
    _fails_on({"title": "x", "due_date": bad}, "due_date")


def test_due_date_default_and_past():
    assert TaskCreate.model_validate({"title": "x"}).due_date is None
    past = TaskCreate.model_validate({"title": "x", "due_date": "2026-01-01"})
    assert str(past.due_date) == "2026-01-01"


def test_task_out_json_shape():
    class Obj:
        id = "abc"
        title = "t"
        due_date = None

    assert json.loads(TaskOut.model_validate(Obj()).model_dump_json()) == {
        "id": "abc",
        "title": "t",
        "due_date": None,
    }
    dated = TaskOut(id="a", title="t", due_date="2026-12-01")
    assert json.loads(dated.model_dump_json())["due_date"] == "2026-12-01"

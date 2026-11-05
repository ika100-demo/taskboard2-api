# Design — 001 Create and list in-memory tasks via POST /tasks and GET /tasks

The HTTP contract is the system contract of `ika100-demo/taskboard2-gitops` `docs/plan/001-create-and-list-tasks.md`
(## Contract), repeated in the spec. It is binding and restated below only as far as this repo's tests need it.

## Decisions

- **App factory.** `main.py` gets `create_app() -> FastAPI`, which builds a new app with its own, empty task store
  (`app.state.task_store`). The module keeps `app = create_app()` so the Dockerfile's
  `uvicorn taskboard2_api.main:app`, `tests/conftest.py` and `tests/test_metrics.py` keep working unchanged.
  Every call returns a fresh, empty store: that is how tests get a "freshly started service" (AC-001.4, .5, .6, .8,
  .9) and how AC-001.12 (restart) is shown in-process (build a second app, list, get `[]`). Logging and tracing
  setup stay at module level (process-wide, run once); the Prometheus metrics are module globals in `metrics.py`, so
  adding `MetricsMiddleware` to several apps registers nothing twice.
- **Store behind a small interface.** A `TaskStore` protocol with `add` and `list_all`, one implementation
  `InMemoryTaskStore` (a Python list in insertion order, guarded by a `threading.Lock` because FastAPI runs sync
  endpoints in a thread pool). The store generates the id (`str(uuid.uuid4())`). A later persistence spec swaps the
  implementation in `create_app()` without touching the router.
- **Validation with pydantic, strict.** One request model; FastAPI's default `RequestValidationError` handler
  produces exactly the contract's 422 format (`{"detail": [{"loc": ["body", <field>], "msg", "type"}]}`), including
  `loc: ["body"]` for a non-object body and `["body", <pos>]` for invalid JSON. No custom exception handler.
  Validation runs before the endpoint body, so on any 422 the store is never called (AC-001.7, .8, .10).
- **`title`** uses `StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)`: strict
  rejects `123`, `true` and `null`; stripping happens before the length check, so `"   "` fails and 200 characters
  surrounded by spaces pass (AC-001.7, .8, .9).
- **`due_date` is parsed by our own before-validator, not by pydantic's `date`.** Pydantic's lax `date` parsing
  accepts integers (Unix timestamps) and some date-time strings, which the contract rejects. The field is
  `Annotated[datetime.date | None, BeforeValidator(parse_due_date)]`; `parse_due_date` returns `None` for `None`,
  raises `ValueError` for any non-`str`, requires `re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)` (ASCII digits
  only; `fullmatch`, so no trailing newline slips through; Python 3.12's `fromisoformat` would otherwise also accept
  `20261201` and date-times), then returns `datetime.date.fromisoformat(value)` (rejects `2026-02-30`). Each
  `ValueError` becomes a validation error with `loc` `["body", "due_date"]` (AC-001.10). Past dates are not checked
  against today (AC-001.11).
- **Schemas and store stay independent.** `TaskOut` uses `from_attributes=True` and is built with
  `TaskOut.model_validate(task)` in the router, so `task_schemas.py` never imports `task_store.py`.
- No ADR: the factory and store are local to this service and documented here.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard2_api/task_store.py` | `Task` (frozen dataclass), `TaskStore` protocol, `InMemoryTaskStore` | new |
| `src/taskboard2_api/task_schemas.py` | `TaskCreate` (request, validation rules), `TaskOut` (response) | new |
| `src/taskboard2_api/tasks_api.py` | `router` with `POST /tasks`, `GET /tasks`; `get_task_store` dependency | new |
| `src/taskboard2_api/main.py` | `create_app()`; module-level `app = create_app()` | changed |

### Public interfaces (signatures only)

```python
# task_store.py
@dataclass(frozen=True, slots=True)
class Task:
    id: str
    title: str
    due_date: datetime.date | None

class TaskStore(Protocol):
    def add(self, title: str, due_date: datetime.date | None) -> Task: ...
    def list_all(self) -> list[Task]: ...      # a copy, oldest first

class InMemoryTaskStore:                       # implements TaskStore
    def __init__(self) -> None: ...

# task_schemas.py
Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
def parse_due_date(value: object) -> datetime.date | None: ...
DueDate = Annotated[datetime.date | None, BeforeValidator(parse_due_date)]

class TaskCreate(BaseModel):                   # extra fields ignored (pydantic default)
    title: Title
    due_date: DueDate = None

class TaskOut(BaseModel):                      # model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    due_date: datetime.date | None             # serialized as "YYYY-MM-DD" or null, always present

# tasks_api.py
router: APIRouter                              # POST /tasks (status_code=201, response_model=TaskOut),
                                               # GET /tasks (response_model=list[TaskOut])
def get_task_store(request: Request) -> TaskStore: ...   # returns request.app.state.task_store

# main.py
def create_app() -> FastAPI: ...
app: FastAPI                                   # = create_app()
```

## Contract

Base URL: the service root. JSON in and out. No authentication.

**Task object** — exactly three fields:

| Field | Type | Notes |
|---|---|---|
| `id` | string | UUID4, canonical text form, generated by the service, unique within the process |
| `title` | string | trimmed, 1 to 200 characters |
| `due_date` | string or `null` | `YYYY-MM-DD`, always present, `null` when not given |

**`POST /tasks`** — body a JSON object:

| Field | Required | Rules |
|---|---|---|
| `title` | yes | JSON string only (no coercion); trimmed (`str.strip()`), then 1 to 200 characters (AC-001.7, .8, .9) |
| `due_date` | no | absent or `null` = no due date; else a JSON string matching `YYYY-MM-DD` that is a real calendar date (AC-001.2, .10, .11) |

Unknown fields are ignored.

- `201 Created`, body the task object (AC-001.1, .2, .9, .11).
- `422 Unprocessable Content`, body `{"detail": [{"loc": [...], "msg": str, "type": str}, ...]}`; the last element of
  `loc` is `"title"` or `"due_date"` for a field error (both present when both are invalid); `loc` is `["body"]` or
  `["body", <pos>]` when the body is not JSON or not an object. Nothing is stored. Tests depend only on the status and
  the field name in `loc`, never on `msg` or `type`.

**`GET /tasks`** — no parameters (unknown query parameters ignored).

- `200 OK`, body a JSON array of task objects, oldest first, each equal to the object its `POST` returned; `[]` when
  none (AC-001.3, .4, .5, .6, .12).

Other statuses (`404`, `405`, `500`) come from the framework and are outside this feature.

### For the acceptance tests

- In-process tests build their own app per test: `TestClient(create_app())` from `taskboard2_api.main`. That is a
  freshly started service. AC-001.12: create tasks on one `create_app()` instance, then list on a second one and
  expect `[]`.
- Smoke tests (AC-001.1, .2, .3, .7, .10) follow `tests/test_smoke_health.py`: `@pytest.mark.smoke`, the
  `smoke_base_url` fixture, `urllib.request` with `timeout=10`; never assume an empty list (find own task by `id`,
  for a 422 compare list lengths before and after).

## Data

None persisted. `InMemoryTaskStore` holds a `list[Task]` for the life of the process (non-goal: persistence, more
than one replica).

## Risks

- Several uvicorn workers or replicas would each have their own list. The Dockerfile starts one worker and the
  gitops entry runs `replicas: 1`; both must stay so (system plan).
- Memory grows without bound with the number of tasks; acceptable for a try-out service without persistence.

---
spec_id: 001-create-and-list-in-memory-tasks-via-post
shape: service-python
spec_hash: 0ca2a8aa41fb
summary: POST /tasks and GET /tasks backed by a per-app in-memory store, with strict pydantic validation
tasks:
  - id: t1
    title: Add Task model, TaskStore protocol and InMemoryTaskStore
    files: [src/taskboard2_api/task_store.py, tests/test_task_store.py]
    covers: [AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.12]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Add TaskCreate and TaskOut schemas with strict title and due_date validation
    files: [src/taskboard2_api/task_schemas.py, tests/test_task_schemas.py]
    covers: [AC-001.1, AC-001.2, AC-001.7, AC-001.8, AC-001.9, AC-001.10, AC-001.11]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Add the /tasks router and the create_app() factory
    files: [src/taskboard2_api/tasks_api.py, src/taskboard2_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8, AC-001.9, AC-001.10, AC-001.11, AC-001.12]
    parallel_safe: false
    depends_on: [t1, t2]
    done: true
---

# Plan — 001 Create and list in-memory tasks via POST /tasks and GET /tasks

Design: [design.md](design.md) (contract, module interfaces, validation rules). No gitops change: the component is
already exposed in dev with `replicas: 1`, no new env vars or resources (system plan, "gitops-app PR").

Levels: t1, t2 (parallel) → t3. t1 and t2 do not import each other.

## t1 — Add Task model, TaskStore protocol and InMemoryTaskStore

**Files:** src/taskboard2_api/task_store.py, tests/test_task_store.py
**Covers:** AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.12
**Goal:** the process-local store that keeps tasks in creation order behind a small interface, so the router never
depends on the list itself and a later spec can swap the storage.

**Implementation notes:**
- `Task`: frozen, slotted dataclass `id: str`, `title: str`, `due_date: datetime.date | None`.
- `TaskStore`: `typing.Protocol` with `add(title, due_date) -> Task` and `list_all() -> list[Task]`.
- `InMemoryTaskStore`: a `list[Task]` plus a `threading.Lock` around append and copy; `add` generates
  `str(uuid.uuid4())` and appends; `list_all` returns a shallow copy, oldest first.
- The store does no validation (that is t2's job) and has no module-level instance: each `InMemoryTaskStore()` starts
  empty.
- Unit tests in `tests/test_task_store.py`: empty on creation, order preserved, distinct ids for equal titles,
  returned list is a copy, two instances do not share state. mypy strict clean.

**Done when:** the unit tests pass and `devbox run quality` is green. The acceptance tests for the covered criteria
pass only after t3.

## t2 — Add TaskCreate and TaskOut schemas with strict title and due_date validation

**Files:** src/taskboard2_api/task_schemas.py, tests/test_task_schemas.py
**Covers:** AC-001.1, AC-001.2, AC-001.7, AC-001.8, AC-001.9, AC-001.10, AC-001.11
**Goal:** the pydantic request and response models that carry every validation rule of the contract, so FastAPI's
default handler yields the contract's 422 format with the right field in `loc`.

**Implementation notes:**
- `Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]`.
- `parse_due_date(value: object) -> datetime.date | None`: `None` → `None`; non-`str` → `ValueError`; must
  `re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)`, else `ValueError`; then `datetime.date.fromisoformat(value)`
  (its `ValueError` for `2026-02-30` propagates). No comparison with today.
- `DueDate = Annotated[datetime.date | None, BeforeValidator(parse_due_date)]`; `TaskCreate(title: Title,
  due_date: DueDate = None)`, default `extra` (ignore).
- `TaskOut(id: str, title: str, due_date: datetime.date | None)` with `model_config = ConfigDict(from_attributes=True)`,
  so t3 builds it with `TaskOut.model_validate(task)`; no import of `task_store`. `due_date` always serializes,
  `null` included.
- Unit tests in `tests/test_task_schemas.py` against `TaskCreate.model_validate` / `model_validate_json`: missing,
  `123`, `true`, `null`, `""`, `"   "` titles fail on `title`; 200 chars (with and without surrounding spaces) pass,
  201 fail; `"  Buy milk  "` becomes `"Buy milk"`; `"tomorrow"`, `"2026-02-30"`, `"2026-12-01T10:00:00Z"`,
  `20261201`, `"20261201"` fail on `due_date`; `"2026-01-01"` passes; `TaskOut` JSON has exactly
  `id`, `title`, `due_date` with `"2026-12-01"` / `null`.

**Done when:** the unit tests pass and `devbox run quality` is green. The acceptance tests pass only after t3.

## t3 — Add the /tasks router and the create_app() factory

**Files:** src/taskboard2_api/tasks_api.py, src/taskboard2_api/main.py
**Covers:** AC-001.1 to AC-001.12
**Goal:** expose `POST /tasks` and `GET /tasks` exactly as in the contract, with a fresh store per app instance.

**Implementation notes:**
- `tasks_api.py`: `router = APIRouter()`; `get_task_store(request: Request) -> TaskStore` returns
  `request.app.state.task_store`.
- `POST /tasks`: sync handler, `status_code=201`, `response_model=TaskOut`, body `TaskCreate`; calls
  `store.add(body.title, body.due_date)` and returns `TaskOut.model_validate(task)`. Validation failures never reach
  the handler, so nothing is stored on 422.
- `GET /tasks`: sync handler, `response_model=list[TaskOut]`, returns `store.list_all()` mapped through
  `TaskOut.model_validate`. No query parameters declared.
- `main.py`: move app construction into `create_app() -> FastAPI` (FastAPI instance, `MetricsMiddleware`,
  `/health`, `/ready`, `/ping`, `/metrics`, `include_router(tasks_api.router)`,
  `app.state.task_store = InMemoryTaskStore()`); keep `app = create_app()` at module level and keep
  `configure_logging` / tracing setup at module level, outside the factory.
- Do not change `tests/conftest.py`, `tests/test_metrics.py` or the Dockerfile; they keep using `main:app`.
- Every response model field present in the JSON (`due_date: null` not dropped): do not set
  `response_model_exclude_none`.

**Done when:** all acceptance tests for AC-001.1 to AC-001.12 pass in-process (`TestClient(create_app())`),
the existing health, metrics and tracing tests still pass, and `devbox run ci` is green (coverage gate included).

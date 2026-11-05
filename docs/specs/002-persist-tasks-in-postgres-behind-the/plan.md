---
spec_id: 002-persist-tasks-in-postgres-behind-the
shape: service-python
spec_hash: db81cd5eff67
summary: PostgresTaskStore (psycopg 3, null pool, lazy schema under advisory lock) selected by DATABASE_URL, 503 on store failure
tasks:
  - id: t1
    title: Add psycopg dependencies, TaskStoreUnavailable and PostgresTaskStore
    files: [pyproject.toml, uv.lock, src/taskboard2_api/task_store.py, src/taskboard2_api/postgres_task_store.py, tests/test_postgres_task_store.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7, AC-002.9]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t2
    title: Select the store from DATABASE_URL in create_app() and map TaskStoreUnavailable to 503
    files: [src/taskboard2_api/main.py, docs/env-vars.md]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7, AC-002.8, AC-002.9, AC-002.10, AC-002.11]
    parallel_safe: false
    depends_on: [t1]
---

# Plan — 002 Persist tasks in Postgres behind the existing TaskStore, answering 503 when the database is down

Design: [design.md](design.md) (decisions, interfaces, 503 contract, test setup). ADR:
[docs/adr/001-postgres-task-persistence.md](../../adr/001-postgres-task-persistence.md).

Levels: t1 → t2. t2 imports `PostgresTaskStore` and `TaskStoreUnavailable` from t1. No gitops task: the `postgres`
resource and `DATABASE_URL` for taskboard2-api are wired by the system plan's gitops part. `tasks_api.py`,
`task_schemas.py`, `tests/conftest.py` and the Dockerfile do not change.

## t1 — Add psycopg dependencies, TaskStoreUnavailable and PostgresTaskStore

**Files:** pyproject.toml, uv.lock, src/taskboard2_api/task_store.py, src/taskboard2_api/postgres_task_store.py, tests/test_postgres_task_store.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7, AC-002.9
**Goal:** a `TaskStore` implementation on Postgres that never connects at construction, creates its table lazily and
race-free, keeps creation order, and turns every database failure into `TaskStoreUnavailable`.

**Implementation notes:**
- `pyproject.toml`: add `psycopg[binary]>=3.2` and `psycopg-pool>=3.2` to `dependencies`, `testcontainers[postgres]>=4.8`
  to the `dev` extra. Regenerate `uv.lock` through the repo's recipes (`devbox shell` runs `uv sync --all-extras`;
  `devbox run test` re-locks via `uv run`); never call `uv add`/`pip` directly. The Dockerfile's `uv sync --locked`
  must pass with the new lock.
- `task_store.py`: add `class TaskStoreUnavailable(Exception)` with a docstring; nothing else changes.
- `postgres_task_store.py`: `PostgresTaskStore(conninfo: str)` opens
  `NullConnectionPool(conninfo, max_size=10, timeout=2.0, open=True, name="taskboard2-api-tasks",
  kwargs={"connect_timeout": 2, "options": "-c statement_timeout=3000", "application_name": "taskboard2-api"})`.
- Lazy schema: `_schema_ready` flag plus `threading.Lock`; while false, inside the checked-out connection run
  `SELECT pg_advisory_xact_lock(SCHEMA_LOCK_KEY)` and the spec's `CREATE TABLE IF NOT EXISTS tasks (...)` verbatim in
  one transaction, commit, then set the flag. A failure leaves it false.
- `add`: `uuid.uuid4()`, `INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)` with bound parameters, one
  transaction; return `Task(id=str(id), title=title, due_date=due_date)`.
- `list_all`: `SELECT id, title, due_date FROM tasks ORDER BY seq`; map to `Task(str(id), title, due_date)`.
- Wrap each public operation so any `psycopg.Error` (includes `PoolTimeout`, `PoolClosed`) becomes
  `raise TaskStoreUnavailable() from exc`. No retry, no background thread.
- `close()`: closes the pool, safe to call twice.
- `tests/test_postgres_task_store.py`: unit tests against a testcontainers Postgres (`driver=None`, fresh database
  per test): empty list on a new database, order kept, two stores on one database see each other's tasks, a second
  store on an existing table works, concurrent first calls from two stores both succeed, unreachable conninfo
  (`127.0.0.1:1`) raises `TaskStoreUnavailable` within 5 s and the constructor does not raise. mypy strict clean.

**Done when:** the unit tests pass, `devbox run quality` is green and `uv.lock` contains psycopg, psycopg-pool and
testcontainers. The acceptance tests pass only after t2.

## t2 — Select the store from DATABASE_URL in create_app() and map TaskStoreUnavailable to 503

**Files:** src/taskboard2_api/main.py, docs/env-vars.md
**Covers:** AC-002.1 to AC-002.11
**Goal:** the service uses Postgres whenever `DATABASE_URL` is set, answers the contract's `503` on store failure,
and otherwise behaves exactly as in spec 001.

**Implementation notes:**
- In `create_app()`, read `os.environ.get("DATABASE_URL", "")` at call time: non-empty → `PostgresTaskStore(url)`,
  else `InMemoryTaskStore()`; assign to `app.state.task_store`. Log `event="task_store_selected"`,
  `backend="postgres"|"memory"` via structlog; never log the URL.
- Register `app.add_exception_handler(TaskStoreUnavailable, ...)` returning
  `JSONResponse(status_code=503, content={"detail": "Task store unavailable"})`; log a warning with
  `event="task_store_unavailable"` and `error=type(exc.__cause__).__name__`, no driver message.
- Add a `lifespan` async context manager that does nothing on startup and calls `store.close()` on shutdown when the
  store has a `close` attribute; pass it to `FastAPI(...)`.
- Keep `/health` and `/ready` independent of the store; keep `configure_logging`/tracing at module level and
  `app = create_app()` at the bottom.
- `docs/env-vars.md`: new "Persistence" section with `DATABASE_URL` (default unset → in-memory store, tests and local
  runs only; set by the platform from the `postgres` resource; libpq URI).
- Existing spec 001 acceptance, smoke, health, metrics and tracing tests must still pass unchanged (they run without
  `DATABASE_URL`).

**Done when:** all acceptance tests for AC-002.1 to AC-002.9 and AC-002.11 pass in-process against testcontainers
Postgres, the spec 001 tests still pass, and `devbox run ci` is green (coverage gate included). AC-002.10 is
verified by the existing smoke tests against the dev URL after deploy.

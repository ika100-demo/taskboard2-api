# Verification — 001 Create and list in-memory tasks via POST /tasks and GET /tasks

**Result:** pass
**Commit:** ebf5ebc · **Base:** 078fc1c · **Trace:** 12/12 criteria named by tests (smoke: AC-001.1, .2, .3, .7, .10 also in `tests/test_smoke_tasks.py`)

Test run (phase 3): `devbox run ci` green; ruff and mypy clean, 51 passed, 7 skipped (smoke, no `SMOKE_BASE_URL`), coverage 96 %, pip-audit, detect-secrets and bandit passed. The acceptance and smoke tests are unchanged since the red commit `f736c21` (`git diff f736c21..HEAD -- tests` touches only the new unit-test files).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks_acceptance.py::test_create_task_title_only`, `tests/test_smoke_tasks.py::test_smoke_ac_001_1_create_task_title_only` | `src/taskboard2_api/tasks_api.py:18-22`, `src/taskboard2_api/task_schemas.py:36-41`, `src/taskboard2_api/task_store.py:35` | asserts 201, exactly the keys `{id, title, due_date}`, non-empty string id, `due_date is None` |
| AC-001.2 | met | `test_create_task_with_due_date`, `test_smoke_ac_001_2_create_task_with_due_date` | `src/taskboard2_api/task_schemas.py:17-28` | asserts 201, title and `"2026-12-01"` |
| AC-001.3 | met | `test_created_task_is_listed`, `test_smoke_ac_001_3_created_task_is_listed` | `src/taskboard2_api/tasks_api.py:25-28`, `src/taskboard2_api/task_store.py:40-42` | `matches == [created]` proves exactly one element with that id and equality to the creation response; other tasks ignored |
| AC-001.4 | met | `test_fresh_service_lists_empty` | `src/taskboard2_api/main.py:31` (fresh store per `create_app()`) | asserts 200 and `[]` |
| AC-001.5 | met | `test_list_is_in_creation_order` | `src/taskboard2_api/task_store.py:36-37` (list append under lock) | asserts the id list equals `[A, B, C]` ids exactly (also proves length 3) |
| AC-001.6 | met | `test_same_title_gets_distinct_ids` | `src/taskboard2_api/task_store.py:35` (`uuid.uuid4()`) | asserts length 2, both titles `"Buy milk"`, ids differ |
| AC-001.7 | met | `test_invalid_title_rejected` (6 cases: missing, `123`, `true`, `null`, `""`, `"   "`), `test_smoke_ac_001_7_invalid_title_rejected` | `src/taskboard2_api/task_schemas.py:9-12` (`strict=True, strip_whitespace=True, min_length=1`) | asserts 422, a `detail` entry with `loc[-1] == "title"`, list not longer afterwards. Smoke test uses `" "` instead of `"   "`; same class of input, the in-process test uses the exact value |
| AC-001.8 | met | `test_title_length_limit` | `src/taskboard2_api/task_schemas.py:11` (`max_length=200`, stripping before length) | asserts 201 chars (plain and space-padded) give 422 on `title` and `[]` afterwards; 200 chars plain and space-padded give 201 with the 200-char title |
| AC-001.9 | met | `test_title_is_trimmed` | `src/taskboard2_api/task_schemas.py:11` (`strip_whitespace=True`) | asserts trimmed title in POST response and in GET list |
| AC-001.10 | met | `test_invalid_due_date_rejected` (`"tomorrow"`, `"2026-02-30"`, `"2026-12-01T10:00:00Z"`, `20261201`), `test_smoke_ac_001_10_invalid_due_date_rejected` | `src/taskboard2_api/task_schemas.py:17-25` (non-str rejected l.21, `fullmatch` l.23, `fromisoformat` l.25) | asserts 422, `loc[-1] == "due_date"`, list not longer afterwards |
| AC-001.11 | met | `test_past_due_date_accepted` | `src/taskboard2_api/task_schemas.py:17-25` (no comparison with today) | asserts 201 and `"2026-01-01"`; the date is in the past relative to any run date from 2026-01-02 on, so no clock fixing is needed |
| AC-001.12 | met | `test_restart_loses_tasks` | `src/taskboard2_api/main.py:27-31,57` | a second `create_app()` instance stands in for the restart, as `design.md` specifies; asserts 200 and `[]` after the first instance holds one task |

## Non-goals

None of the excluded behaviour is implemented. No persistence (store is a per-app list, `task_store.py:31`), no UI, no multi-replica coordination, no query parameters declared on `GET /tasks` (`tasks_api.py:25-26`), no update, complete or delete routes, no authentication, no idempotency key. ✔

## Deviations from the plan

- Every changed source and test file lies within a task's `files`, except `tests/test_tasks_acceptance.py` and `tests/test_smoke_tasks.py`. Those come from the red acceptance-test commit `f736c21`, which happens before the plan tasks run, so this is expected. Acceptable.
- All three tasks are `done: true`.
- `tests/conftest.py`, `tests/test_metrics.py` and the Dockerfile are unchanged, as the t3 notes require. ✔
- `get_task_store(request)` is called directly inside the handlers (`tasks_api.py:21,28`) rather than injected with `Depends`. The signature matches the design, and the design calls it a "dependency" without requiring `Depends`. This has no effect on behaviour or the contract. Acceptable. A later persistence spec that wants to override it in tests would need `Depends`.

## Contract

Matches `design.md`. Both routes return the documented status codes (201 / 200). The task object has exactly three fields, and `due_date` is serialized as `YYYY-MM-DD` or `null` because `response_model_exclude_none` is not set. A 422 uses FastAPI's default validation format, and there is no custom handler. Unknown body fields are ignored (pydantic default `extra`). The store is created in `create_app()`, and `app = create_app()` stays at module level (`main.py:57`). Logging and tracing setup remain at module level (`main.py:18-20`). ✔

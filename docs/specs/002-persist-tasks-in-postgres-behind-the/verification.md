# Verification — 002 Persist tasks in Postgres behind the existing TaskStore, answering 503 when the database is down

**Result:** pass
**Commit:** f739aa5 · **Base:** 24fe3ad · **Trace:** 11/11 criteria named by tests (AC-002.10 smoke-tagged in `tests/test_smoke_tasks.py`)

Test run (Phase 3): `devbox run ci` green, 74 passed, 7 skipped (smoke, need `SMOKE_BASE_URL`), coverage 94%, quality and security gates green. The acceptance tests in `tests/test_tasks_postgres_acceptance.py` and the smoke file have not changed since the red commit `5dc10c4`.

All test ids below are in `tests/test_tasks_postgres_acceptance.py` unless a different file is named.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `::test_tasks_survive_restart` | `src/taskboard2_api/main.py:36-39`, `src/taskboard2_api/postgres_task_store.py:57-77` | A second `create_app()` on the same URL returns `200` and a list equal to the A, B, C creation bodies, in that order (l.88-90). Order comes from `ORDER BY seq` (l.74). |
| AC-002.2 | met | `::test_new_task_after_restart_has_new_id` | `src/taskboard2_api/postgres_task_store.py:58,62-65` | Checks the `201`, an id that is not among the old ids, and that the list is `[*old, new]`, so the new task comes last. |
| AC-002.3 | met | `::test_two_instances_share_tasks` | `src/taskboard2_api/postgres_task_store.py:70-77` | Tested both ways (one to two, two to one) with exact list equality, so each task appears exactly once, the objects match and both instances return the same order. |
| AC-002.4 | met | `::test_simultaneous_start_on_fresh_database` | `src/taskboard2_api/postgres_task_store.py:46-55` (`pg_advisory_xact_lock` + `CREATE TABLE IF NOT EXISTS`) | Two threads behind a barrier each build an instance, then send GET and POST. The test checks `[200, 201]` per instance, no exceptions, and that both instances list two "Buy milk" tasks. |
| AC-002.5 | met | `::test_fresh_database_lists_empty` | `src/taskboard2_api/postgres_task_store.py:46-55,70-77` | `200` and `[]` on a fresh database. Nothing is migrated from memory. |
| AC-002.6 | met | `::test_unreachable_database_answers_503`, `::test_paused_database_answers_503_and_stores_nothing` | `src/taskboard2_api/postgres_task_store.py:31-42` (connect 2 s, checkout 2 s, statement 3 s), `:66-67,75-76` (wrap `psycopg.Error`), `src/taskboard2_api/main.py:57-65` (503 handler) | `assert_unavailable` checks the status, the `application/json` content type and the exact body. `timed` checks each call takes under 5 s. Covers a refused port and a paused container. After unpause, the list has no "Lost task". |
| AC-002.7 | met | `::test_service_recovers_without_restart` | `src/taskboard2_api/postgres_task_store.py:31` (`NullConnectionPool`: a new connection on each checkout, no background reconnect) | The same client gets a `503` while paused, then `201` for "Back again" and `200` with a list containing the created object. |
| AC-002.8 | met | `::test_invalid_body_is_422_when_database_down` | `src/taskboard2_api/tasks_api.py:19` (the `TaskCreate` body is validated before the handler touches the store, file unchanged) | Uses the dead URL. `{"title": ""}` gives `422` with `loc[-1] == "title"`, and `due_date: "tomorrow"` gives `422` with `loc[-1] == "due_date"`. |
| AC-002.9 | met | `::test_starts_with_database_down_then_recovers` | `src/taskboard2_api/postgres_task_store.py:30-44` (constructor never connects), `src/taskboard2_api/main.py:46-51` (startup does nothing), `:67-75` (probes ignore the store) | The instance is built while the database is paused. The test checks `/health` and `/ready` give `200`, `/tasks` gives `503`, and after unpause the same client gets `200` and `201`. |
| AC-002.10 | met | `tests/test_smoke_tasks.py::test_smoke_ac_001_1_create_task_title_only`, `::test_smoke_ac_001_2_create_task_with_due_date`, `::test_smoke_ac_001_3_created_task_is_listed`, `::test_smoke_ac_001_7_invalid_title_rejected`, `::test_smoke_ac_001_10_invalid_due_date_rejected` (all `@pytest.mark.smoke`) | `src/taskboard2_api/main.py:36-39` (Postgres when the platform sets `DATABASE_URL`) | The spec 001 smoke checks are unchanged apart from the added criterion ids and line wraps. They create `smoke-<uuid>` tasks and find them by id. They have not run yet (skipped in CI) and run against the dev URL after deploy. That run is the final evidence. |
| AC-002.11 | met | `::test_fresh_db_lists_empty` (AC-001.4), `::test_fresh_db_creation_order` (.5), `::test_fresh_db_duplicate_titles` (.6), `::test_fresh_db_title_length_limit` (.8), `::test_fresh_db_title_trimmed` (.9), `::test_fresh_db_past_due_date_accepted` (.11) | `src/taskboard2_api/postgres_task_store.py:57-77`, `src/taskboard2_api/tasks_api.py` + `task_schemas.py` unchanged | Each test asserts the outcome of the spec 001 criterion it names, on a fresh database. Examples: for .8, 201 characters gives `422` on `title` and then `[]`, while 200 characters with or without padding gives `201`. For .11, `201` with `due_date` `"2026-01-01"`. |

## Non-goals

- No migration from memory: the store only reads the `tasks` table. ✔
- No database check in `/ready`: `src/taskboard2_api/main.py:72-75` returns `200` without touching the store. ✔
- No retries: `add` and `list_all` make one attempt and raise. `NullConnectionPool` has no background reconnect workers. ✔
- No HTTP contract change other than the `503`: `tasks_api.py` and `task_schemas.py` are unchanged. ✔
- The in-memory fallback without `DATABASE_URL` stays (`main.py:41-43`), as the spec allows for tests and local runs. The backend in use is logged (`main.py:44`). ✔
- Nothing touches replica counts. ✔

## Deviations from the plan

- `tests/test_tasks_postgres_acceptance.py` (new) and `tests/test_smoke_tasks.py` (criterion-id comments and line wraps only) are not in any task's `files`. They come from the red acceptance-test commit `5dc10c4`, which is expected. The design says the smoke file "runs unchanged", and its behaviour is unchanged. Acceptable.
- `docs/adr/001-postgres-task-persistence.md` and the spec docs are not in any task's `files`. They are planning artefacts that the design links to. Acceptable.
- Both tasks t1 and t2 are `done: true`. No source file was changed outside the plan. `Dockerfile` and `tests/conftest.py` are unchanged, as the plan requires.

## Contract

Matches `design.md`:
- The 503 body is exactly `{"detail": "Task store unavailable"}` as JSON (`main.py:63`).
- The warning log carries only the class name of the cause (`main.py:59-62`), never the URL or the driver message.
- The pool parameters match the design exactly (`postgres_task_store.py:31-42`).
- The schema DDL is the spec's DDL word for word (`:17-24`).
- `SCHEMA_LOCK_KEY = 7_202_002_001` with the transaction-scoped advisory lock (`:15,53`).
- `ORDER BY seq` (`:74`), ids from `uuid4` (`:58`), and `close()` is idempotent (`:79-83`, unit test `tests/test_postgres_task_store.py::test_close_is_idempotent`) and called from the lifespan shutdown.
- Dependencies are `psycopg[binary]>=3.2`, `psycopg-pool>=3.2` and dev `testcontainers[postgres]>=4.8`, and all three are in `uv.lock`. ✔

## Observations (not blocking)

- `statement_timeout` is enforced by the server. If the database becomes unreachable after a connection is already open (a network partition in the middle of a request), the client has no timeout of its own, so that request could take longer than 5 s. With a null pool the window is one request long. No criterion covers it and the tests do not exercise it. A candidate follow-up is TCP keepalive or a `socket` timeout.
- AC-002.10 is only proven once the post-deploy smoke run against `http://taskboard2-api.taskboard2-dev.localhost:8088` is green.

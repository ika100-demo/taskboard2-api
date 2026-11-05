# ADR-001: Persist tasks in Postgres with psycopg 3, a null pool and a service-managed schema

## Status

Accepted (spec 002).

## Context

Spec 002 moves tasks from process memory into the `postgres` resource the platform provides (`DATABASE_URL`). The
service must keep starting and answering its probes while the database is down, answer `503` during an outage and
recover on the next request without a restart and without a background retry loop. Up to two replicas may start at
the same time on an empty database. The schema is a single table.

## Decision

- Driver: psycopg 3 (`psycopg[binary]`, bundled libpq) with `psycopg_pool.NullConnectionPool`: a connection is opened
  in the requesting thread on checkout and closed on return. Connect timeout 2 s, checkout timeout 2 s,
  `statement_timeout` 3 s.
- The service creates its schema itself, idempotently (`CREATE TABLE IF NOT EXISTS`), on the first successful
  connection, inside a transaction holding `pg_advisory_xact_lock` on a fixed key. No migration framework.
- Every driver error surfaces as the domain exception `TaskStoreUnavailable`, mapped to one `503` JSON response.

## Consequences

- Positive: deterministic failure and recovery (no reconnect backoff state), no startup dependency on the database,
  no extra migration job or tool in the image or the gitops repo.
- Negative: one connection setup per request (a few ms in-cluster); at much higher load switch to
  `ConnectionPool` with `check=ConnectionPool.check_connection` and a short `reconnect_timeout`, in a new ADR.
- Schema changes beyond additive, idempotent DDL (renames, data migrations) need a real migration tool; adopting one
  supersedes this ADR.

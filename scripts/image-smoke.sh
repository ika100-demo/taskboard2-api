#!/usr/bin/env bash
# Run taskboard2-api:scan like Kubernetes would (read-only rootfs, /tmp tmpfs, numeric non-root user) and probe it.
# Cases: no DATABASE_URL (in-memory store) and an unreachable DATABASE_URL. Also checks psycopg imports (libpq).
set -euo pipefail
IMG=taskboard2-api:scan
PORT_HOST=${SMOKE_IMAGE_PORT:-18080}

docker run --rm --read-only --tmpfs /tmp --user 10001:10001 "$IMG" \
  python -c "import psycopg, psycopg_pool; print('psycopg', psycopg.__version__, 'impl', psycopg.pq.__impl__)"

run_case() {
  local name=$1; shift
  local cid
  cid=$(docker run -d --rm --read-only --tmpfs /tmp --user 10001:10001 -p "$PORT_HOST:8080" "$@" "$IMG")
  trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' RETURN
  local ok=0
  for _ in $(seq 1 30); do
    if curl -fsS "http://localhost:$PORT_HOST/health" >/dev/null 2>&1; then ok=1; break; fi
    sleep 1
  done
  [ "$ok" = 1 ] || { echo "FAIL ($name): /health"; docker logs "$cid" | tail -20; return 1; }
  for p in /health /ready; do
    echo "$name $p -> $(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT_HOST$p")"
  done
  docker logs "$cid" 2>&1 | tail -5
}

run_case in-memory
run_case unreachable-db -e DATABASE_URL=postgresql://u:p@127.0.0.1:1/db

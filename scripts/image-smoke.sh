#!/usr/bin/env bash
# Runs the built image like Kubernetes would (read-only rootfs, /tmp tmpfs) and probes it.
set -euo pipefail
name=taskboard2-smoke
port=18080
docker rm -f "$name" >/dev/null 2>&1 || true
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$name" --read-only --tmpfs /tmp -p "$port:8080" taskboard2-api:scan >/dev/null
for _ in $(seq 1 30); do curl -fs "localhost:$port/health" >/dev/null 2>&1 && break; sleep 1; done
echo "user: $(docker exec "$name" id -u)"
echo "cmd: $(docker inspect -f '{{.Config.Cmd}}' "$name")"
echo "health: $(curl -s -o /dev/null -w '%{http_code}' "localhost:$port/health")"
echo "ready: $(curl -s -o /dev/null -w '%{http_code}' "localhost:$port/ready")"
echo "post: $(curl -s -w ' %{http_code}' -X POST -H 'content-type: application/json' -d '{"title":"Buy milk"}' "localhost:$port/tasks")"
echo "get: $(curl -s "localhost:$port/tasks")"
docker exec "$name" sh -c 'ps -eo args | grep -c "[u]vicorn"' || true

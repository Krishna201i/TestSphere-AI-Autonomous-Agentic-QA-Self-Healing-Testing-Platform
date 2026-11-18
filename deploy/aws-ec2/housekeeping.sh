#!/bin/sh
# Daily disk cleanup on the instance (run by testsphere-housekeeping.timer):
# Docker images and build cache left by each `docker compose up --build`, and
# repository checkouts left in the data volume. Artifacts (screenshots,
# traces) expire in the app itself (ARTIFACT_RETENTION_DAYS).
set -eu
cd "$(dirname "$0")"

# Ingest deletes its clone after analysis and a patch deletes its temporary
# one when done, so anything here older than 6 hours is a leftover
docker compose exec -T api sh -c '
    find /app/data/repos -mindepth 1 -maxdepth 1 -mmin +360 ! -name patches -exec rm -rf {} +
    find /app/data/repos/patches -mindepth 1 -maxdepth 1 -mmin +360 -exec rm -rf {} +
' 2>/dev/null || true   # no repos folder yet, or the api is down: nothing to do

docker image prune -f
docker builder prune -f --filter until=168h   # keep a week of cache so rebuilds stay quick

df -h / | tail -1

#!/usr/bin/env bash
# Pull-based continuous deployment (run by testsphere-deploy.timer as root).
#
# When ghcr.io/<owner>/testsphere:main points at a new image (CI passed on
# main and .github/workflows/deploy.yml published it), this checks out that
# image's commit (for its compose file and Caddyfile), starts it, and waits
# for https://$DOMAIN/api/health.  If the new version is not healthy within
# HEALTH_SECONDS it puts the previous image and commit back.  Every outcome is
# logged to the journal (journalctl -u testsphere-deploy).
set -euo pipefail

# This file is in the checkout the deploy switches commits in: run from a
# copy, so bash never reads a file that changed under it
if [ -z "${PULL_DEPLOY_COPY:-}" ]; then
  cp "$0" /run/testsphere-pull-deploy.sh
  PULL_DEPLOY_COPY=1 exec bash /run/testsphere-pull-deploy.sh "$@"
fi

APP=/opt/testsphere/app
DIR="$APP/deploy/aws-ec2"
STATE=/opt/testsphere/deployed-digest
REPO="${TESTSPHERE_REPO:-ghcr.io/krishna201i/testsphere}"
HEALTH_SECONDS="${HEALTH_SECONDS:-300}"

exec 9>/run/testsphere-deploy.lock
flock -n 9 || { echo "another deploy is running"; exit 0; }

git_() { git -c safe.directory="$APP" -C "$APP" "$@"; }
env_value() { sed -n "s/^$1=//p" "$DIR/.env" 2>/dev/null | tail -1; }
set_env() {  # set_env IMAGE COMMIT: what compose runs, kept in the folder's .env
  touch "$DIR/.env"
  sed -i '/^TESTSPHERE_IMAGE=/d;/^GIT_COMMIT=/d' "$DIR/.env"
  printf 'TESTSPHERE_IMAGE=%s\nGIT_COMMIT=%s\n' "$1" "$2" >> "$DIR/.env"
}
start() { (cd "$DIR" && ./fetch-env.sh >/dev/null && docker compose up -d --no-build --remove-orphans); }
healthy() {
  local domain; domain=$(env_value DOMAIN)
  for _ in $(seq 1 $((HEALTH_SECONDS / 10))); do
    if curl -sf --max-time 8 "https://$domain/api/health" | grep -q '"status":"ok"'; then return 0; fi
    sleep 10
  done
  return 1
}

docker pull -q "$REPO:main" >/dev/null
digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$REPO:main")
[ "$digest" = "$(cat "$STATE" 2>/dev/null || true)" ] && exit 0  # nothing new

revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$REPO:main")
echo "New image $digest (commit ${revision:0:12})"
previous_image=$(env_value TESTSPHERE_IMAGE); previous_image=${previous_image:-testsphere:latest}
previous_commit=$(git_ rev-parse HEAD)

git_ fetch -q origin
git_ checkout -q --detach "$revision"
set_env "$digest" "${revision:0:7}"
if start && healthy; then
  echo "$digest" > "$STATE"
  echo "Deployed ${revision:0:12}: healthy"
  docker image prune -f --filter "until=168h" >/dev/null || true
  exit 0
fi

echo "Commit ${revision:0:12} is not healthy: rolling back to $previous_image"
git_ checkout -q --detach "$previous_commit"
set_env "$previous_image" "$(git_ rev-parse --short HEAD)"
start
echo "$digest" > "$STATE"  # do not retry the same broken image; the next good one replaces it
if healthy; then echo "Rolled back: healthy"; else echo "Rolled back, but still not healthy: check docker compose logs"; fi
exit 1

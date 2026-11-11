#!/bin/sh
# Nightly jobs (M9, ADR 0025), run by the "jobs" service from the API image:
#   1. back up Postgres (pg_dump, custom format) and the profile pictures into /backups
#   2. delete backups older than BACKUP_DAYS
#   3. delete old anonymous users (python -m app.cleanup, ADR 0024)
# Runs daily at JOBS_AT (UTC, default 03:30). `inrotation-jobs --now` runs once and exits.
set -eu
AT="${JOBS_AT:-03:30}"
KEEP="${BACKUP_DAYS:-14}"

run_once() {
  stamp=$(date -u +%Y%m%d-%H%M)
  echo "$(date -u +%FT%TZ) backup $stamp"
  pg_dump --format=custom --file="/backups/db-$stamp.dump.part" && mv "/backups/db-$stamp.dump.part" "/backups/db-$stamp.dump"
  tar -czf "/backups/avatars-$stamp.tar.gz" -C /avatars .
  find /backups -maxdepth 1 -type f \( -name 'db-*.dump' -o -name 'avatars-*.tar.gz' \) -mtime "+$KEEP" -delete
  echo "$(date -u +%FT%TZ) cleanup"
  cd /app/backend && python -m app.cleanup
  echo "$(date -u +%FT%TZ) done"
}

if [ "${1:-}" = "--now" ]; then
  run_once
  exit 0
fi

while true; do
  now=$(date -u +%s)
  next=$(date -u -d "today $AT" +%s)
  [ "$next" -le "$now" ] && next=$(date -u -d "tomorrow $AT" +%s)
  echo "$(date -u +%FT%TZ) next run at $(date -u -d "@$next" +%FT%TZ)"
  sleep $((next - now))
  run_once || echo "$(date -u +%FT%TZ) jobs FAILED (see above)"
done

#!/usr/bin/env bash
# Install a data bundle from `python -m ingest.release` on the server, switch the API to it, and roll back
# by itself if the API doesn't come up healthy (M9, ADR 0025).
#
#   deploy/install-data.sh /srv/inrotation/releases/inrotation-data-20261107-1200.tar.gz
#   deploy/install-data.sh --use 20261101-0900        # switch back to a version that's still installed
#   deploy/install-data.sh --list
#
# Versions live in $ROOT/data/<version>. $ROOT/data/current is a symlink to the one in use. The newest
# KEEP versions stay, for rollback. Run from the repo root on the server.
set -euo pipefail
ROOT="${INROTATION_ROOT:-/srv/inrotation}"
KEEP="${KEEP:-3}"
COMPOSE=(docker compose -f deploy/compose.yaml)
DATA="$ROOT/data"
mkdir -p "$DATA"

current() { readlink "$DATA/current" 2>/dev/null | xargs -r basename; }

switch_to() {   # point current at a version, recreate the API, wait until it's healthy
  local version="$1" previous
  previous="$(current || true)"
  # Docker creates an empty folder at current if the stack starts before any data is installed. Clear it.
  if [ -d "$DATA/current" ] && [ ! -L "$DATA/current" ]; then
    rmdir "$DATA/current" 2>/dev/null || { echo "$DATA/current is a folder with files in it, not a link. Move it aside and run this again." >&2; return 1; }
  fi
  ln -sfn "$DATA/$version" "$DATA/current.new" && mv -T "$DATA/current.new" "$DATA/current"
  if [ -z "$("${COMPOSE[@]}" ps -q api 2>/dev/null)" ]; then
    echo "Data is now $version. The stack isn't running yet: start it with ${COMPOSE[*]} up -d --build"
    return 0
  fi
  echo "Data is now $version. Restarting the API (startup takes about a minute)..."
  "${COMPOSE[@]}" up -d --force-recreate --no-deps api
  for _ in $(seq 1 40); do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$("${COMPOSE[@]}" ps -q api)" 2>/dev/null || echo starting)"
    if [ "$status" = healthy ]; then echo "API healthy on $version."; return 0; fi
    sleep 5
  done
  echo "The API didn't become healthy on $version. Its log:" >&2
  "${COMPOSE[@]}" logs --tail 40 api >&2 || true
  if [ -n "$previous" ] && [ "$previous" != "$version" ]; then
    echo "Rolling back to $previous." >&2
    ln -sfn "$DATA/$previous" "$DATA/current.new" && mv -T "$DATA/current.new" "$DATA/current"
    "${COMPOSE[@]}" up -d --force-recreate --no-deps api
  fi
  return 1
}

case "${1:-}" in
  --list)
    echo "Installed (current: $(current || echo none)):"
    ls -1 "$DATA" | grep -v '^current' || true
    exit 0 ;;
  --use)
    [ -d "$DATA/${2:?version}" ] || { echo "No version $2 in $DATA" >&2; exit 1; }
    switch_to "$2"; exit $? ;;
  ""|-h|--help)
    sed -n '2,10p' "$0"; exit 0 ;;
esac

BUNDLE="$1"
[ -f "$BUNDLE" ] || { echo "No file $BUNDLE" >&2; exit 1; }
# awk reads the whole listing: `head -1` would close the pipe early, and under pipefail tar's SIGPIPE (exit 141)
# would end the script silently.
VERSION="$(tar -tzf "$BUNDLE" | awk -F/ 'NR == 1 { print $1 }')"
[ -n "$VERSION" ] || { echo "Can't read a version from $BUNDLE" >&2; exit 1; }
if [ -d "$DATA/$VERSION" ]; then echo "Version $VERSION is already installed. Use --use $VERSION to switch to it." >&2; exit 1; fi

echo "Unpacking $VERSION..."
tar -xzf "$BUNDLE" -C "$DATA"
echo "Checking files against the manifest..."
python3 - "$DATA/$VERSION" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
m = json.loads((root / "manifest.json").read_text())
for name, want in m["files"].items():
    h = hashlib.sha256()
    with (root / name).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() != want["sha256"]:
        sys.exit(f"Checksum mismatch: {name}")
print(f"OK: {len(m['files'])} files, catalog schema {m['catalog']['schema_version']}, {m['catalog']['albums']:,} albums")
PY
chmod -R a+rX "$DATA/$VERSION"

if ! switch_to "$VERSION"; then
  echo "Left $VERSION installed but not in use." >&2
  exit 1
fi

# Keep the newest KEEP versions (never the current one).
ls -1dt "$DATA"/*/ | xargs -n1 basename | grep -v -e '^current$' -e "^$(current)$" | tail -n "+$KEEP" | while read -r old; do
  echo "Removing old version $old"; rm -rf "${DATA:?}/$old"
done

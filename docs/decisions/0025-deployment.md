# 0025: Deployment on one server behind Cloudflare (M9)

Status: accepted (2026-11-07). Owner decisions, from the M9 questions:
- **Hosting:** one rented server with Docker Compose, Cloudflare in front.
- **Database:** Postgres on the same server, with nightly backups.
- **Visibility:** a private preview behind one shared password, until the dataset and cover-art licensing is checked. Removed 2026-11-10 (see the last revision).
- **CI:** none for now.

Steps are in [docs/deploy.md](../deploy.md).

## Revision (2026-11-08): OVHcloud VPS
The owner is using an OVHcloud VPS. Its Edge Network Firewall shapes the setup:
- **Stateless, at most 20 rules, one source range per rule.** The rule set is: SSH from the owner's address, TCP established, UDP, ICMP, one rule for each of Cloudflare's 15 IPv4 ranges (any port), and deny the rest.
- **IPv4 only.** So `deploy/.env` publishes 80 and 443 on `0.0.0.0` only (`HTTP_PORT`, `HTTPS_PORT`, no code change), sshd uses `AddressFamily inet`, and Cloudflare has only an `A` record.
- **Sign-in:** the Ubuntu image signs in as `ubuntu` with sudo, so there's no separate deploy user.

## Shape
- **Services** (`deploy/compose.yaml`):
  - **`db`:** Postgres 16, with a named volume and no published port.
  - **`migrate`:** runs `alembic upgrade head` once, and the API waits for it.
  - **`api`:** one uvicorn worker. The engine holds the listening matrix and item kNN's scaled copies, about 2.0 GB at rest and 2.3 GB in use (re-measured 2026-11-10), and a second worker would double that.
  - **`web`:** Caddy with the Vite build baked in.
  - **`jobs`:** the API image, running `deploy/jobs.sh`.
- **One origin:** Caddy serves the site and proxies `/api`, so the browser never makes cross-origin calls. `INROTATION_CORS_ORIGINS` is empty when deployed.
- **HTTPS:** Cloudflare (Full, strict) talks to Caddy, which uses a Cloudflare Origin Certificate. No ACME is needed, which matters because Let's Encrypt challenges are awkward behind Cloudflare's proxy. `CADDY_TLS=none` serves plain HTTP for local tests.
- **Files:**
  - **Data:** a read-only mount of `/srv/inrotation/data/current`.
  - **Covers and profile pictures:** writable mounts. Covers are kept outside the data versions because they're keyed by album and outlive any model.

## Real visitor addresses
The Ask and sign-in limits (ADR 0014, 0024) count devices by network address. Behind Cloudflare and Caddy, the
connection comes from Caddy, so:
- **Caddy** trusts `CF-Connecting-IP` only from Cloudflare's published ranges (`trusted_proxies`). It passes `{client_ip}` to the API as `X-Real-IP`.
- **The API** reads `X-Real-IP` only with `INROTATION_TRUST_PROXY=1`, which the image sets. It's only reachable through Caddy.

Checked locally: 21 sign-ins with faked `CF-Connecting-IP` and `X-Real-IP` headers all counted as one device, and the device was paused after 20.

## Private preview (removed 2026-11-10)
- **How:** Caddy's `forward_auth` asks `GET /api/preview/check` before every request except `/preview`, `/api/preview/*` and `/api/health`.
- **Without `INROTATION_PREVIEW_PASSWORD`:** every check passes, so going public is one setting.
- **With it:** page loads without the cookie are redirected to `/preview`, and API calls get 401.
- **The form** sets an HttpOnly, SameSite=Lax cookie, marked Secure behind HTTPS. Its value is an HMAC of the password keyed with `INROTATION_SECRET`, so a new password signs everyone out.
- **Limits:** wrong passwords count toward the per-device sign-in limit. The form only redirects to paths on the same site.
- **Why not HTTP basic auth:** the site already sends `Authorization: Bearer` for sessions, and the two would collide.

## Versioned data (`python -m ingest.release`, `deploy/install-data.sh`)
- **What's in a bundle:** only what the API reads: `model/albums.parquet`, `model/interactions.parquet` (the matrix is rebuilt from them at startup), `report.json`, `catalog.db` and `album_map.json`. A manifest records the version, catalog schema and counts, and each file's SHA-256. The full data makes a 565 MB bundle in 46 s.
- **Installing:** the server script checks every hash, unpacks to `data/<version>`, flips the `current` symlink, recreates the API and waits for it to be healthy. If it isn't healthy within about 3 minutes, the script flips back. It keeps 3 versions, and `--use` switches between them.
- **Checked locally:** a bundle was built, unpacked and verified, and the API started from it alone and served albums and similar albums.

## Nightly jobs (`deploy/jobs.sh`)
- **Backups:** `pg_dump --format=custom` and a tar of the profile pictures, kept for `BACKUP_DAYS` (14).
- **Cleanup:** `python -m app.cleanup` (ADR 0024).
- **Schedule:** a sleep loop to `JOBS_AT` (03:30 UTC) instead of cron, so the image needs no cron daemon. `--now` runs once.
- **Off-server copies are manual** for now, by rsync. That's a known gap: one disk holds both the database and its backups.

## Not done or not verified
- **No real server has been set up yet.** Everything above ran in local Docker (Docker Desktop, 8 GB), with `CADDY_TLS=none` on port 8088. The Cloudflare-specific parts (origin certificate, `CF-Connecting-IP` from real Cloudflare addresses) can only be checked on the server.
- **No CI, and no git repository.** Code reaches the server by rsync.
- **Covers on Cloudflare's edge** need a Cache Rule (docs/deploy.md section 5).

## Revision (2026-11-10): no private preview
The owner asked for the password-protected site to be removed. `backend/app/preview.py`, its tests, the `forward_auth` block in the Caddyfile and `INROTATION_PREVIEW_PASSWORD` are gone, so the deployed site is public from the first start. The licensing check (dataset terms, cover art) is still open and is now a step before the site goes up, not before a password comes off. The Cloudflare Cache Rule for covers moved into setup, since there's no later launch step.

# Deploying In Rotation (M9)

One OVHcloud VPS runs everything with Docker Compose: Postgres, the API, Caddy (the site, HTTPS and the `/api`
proxy) and a nightly jobs container. Cloudflare sits in front. The site is public as soon as it's up (the password-protected preview was
removed 2026-11-10 at the owner's request). The decisions are in
[ADR 0025](decisions/0025-deployment.md).

```
visitor ─▶ Cloudflare ─▶ Caddy :443 ─┬─ /api/* ─▶ api:8000 ─▶ db (Postgres)
                                     └─ site files (/srv)
            jobs: nightly pg_dump + avatars backup, then python -m app.cleanup
```

Measured on the full data (local Docker, 2026-11-07): the API image is 951 MB, and the site image is 50 MB. The API
starts in about 7 s and uses about 2.0 GB of memory at rest, about 2.3 GB after 25 tastes' For You lists (measured 2026-11-10 with item kNN, Docker Desktop). The data bundle is 565 MB, and covers take another 500 MB.

The steps run in this order:
1. An SSH key on your Mac.
2. The VPS.
3. The firewall.
4. Securing SSH and installing Docker.
5. Cloudflare.
6. Copying up the code, settings and data.
7. Starting the stack and checking it.

OVHcloud renames things in its Control Panel now and then, so a menu may be worded a little differently from this guide.

## 1. An SSH key
An SSH key is how you sign in to the server without a password. It's a pair of files on your Mac:
- **The private key** (`~/.ssh/id_ed25519`) never leaves your Mac.
- **The public key** (`~/.ssh/id_ed25519.pub`) goes on the server.

When you connect, the server checks that you hold the private key that matches. Bots try passwords against every server on the internet all day, but nobody can guess a key. Once password sign-in is off (section 4), the key is the only way in.

1. **Check for a key:** run `ls ~/.ssh/*.pub`. If it lists `id_ed25519.pub`, you already have one: skip to step 3.
2. **Make one:**
   - Run `ssh-keygen -t ed25519 -C "in-rotation laptop"`. The text after `-C` is just a label.
   - Press Enter to accept the default file.
   - Give it a passphrase. It protects the private key if your Mac is ever lost, and macOS can remember it in the Keychain.
3. **Copy the public key:** run `pbcopy < ~/.ssh/id_ed25519.pub`. It's one line starting with `ssh-ed25519`. Copy only the `.pub` file, never the one without `.pub`.
4. **Back up `~/.ssh`** (Time Machine is fine). If you lose the private key, you'll have to use the KVM console to get back in (see "Locked out" at the end).

## 2. The VPS
- **Size:** at least **8 GB of memory** and 40 GB of disk. The API alone uses about 2.0-2.3 GB, and 4 GB would be tight once Postgres and a busy API share it.
- **Image:** Ubuntu 24.04.
- **SSH key:** paste the public key from step 1 at the SSH key step of the order.
  - If the VPS already exists and you got a password by email instead, use **Reinstall** on the VPS page. Choose Ubuntu 24.04 and your key. Reinstalling wipes the VPS, which doesn't matter while it's empty.
- **Your user is `ubuntu`, not `root`.** OVHcloud's Ubuntu image puts your key on a user called `ubuntu`, which can use `sudo`. Root sign-in is already off.
- **Note the addresses** on the VPS page (Control Panel > Bare Metal Cloud > Virtual Private Servers > your VPS): the IPv4 address, and the IPv6 address if one is shown.

Connect for the first time:
```
ssh ubuntu@<VPS IPv4 address>
```
It asks you to confirm the server's fingerprint: type `yes`.

**Shortcut:** add this to `~/.ssh/config` on your Mac. Then `ssh inrotation` connects, and `inrotation:` works in `scp` and `rsync` in place of `ubuntu@<address>:`. The rest of this guide uses it.
```
Host inrotation
  HostName <VPS IPv4 address>
  User ubuntu
```

## 3. The firewall (OVHcloud Edge Network Firewall)
Use OVHcloud's firewall, not `ufw` on the server. Docker writes its own network rules that go around `ufw`, so with only `ufw`, port 443 would still be open to everyone. The Edge Network Firewall filters traffic before it reaches the VPS, so Docker can't get around it.

The goal:
- **SSH (port 22):** only from your own address.
- **The site (80 and 443):** only from Cloudflare. Then nobody can skip Cloudflare and reach Caddy directly, which matters because Caddy trusts the visitor address Cloudflare passes on.

**Three limits** shape the rules:
- **20 rules at most,** and each rule takes **one** source range.
- **It's stateless.** It doesn't remember connections, so replies to the server's own outgoing traffic need rules of their own. That outgoing traffic includes installing Docker, pulling images, DNS and calling Gemini.
- **It filters IPv4 only.** Section 4 closes the IPv6 side.

It filters only incoming traffic. Everything the server sends out is allowed.

**Find your own address** on your Mac: `curl -4 ifconfig.me`. Home addresses change now and then. When yours does, update rule 0 (see "Locked out").

**Set it up:**
1. Go to Control Panel > **Bare Metal Cloud > Network > Public IP Addresses**.
2. Click `...` next to the VPS's IPv4 address, then **Edge Network Firewall configuration**.
3. Create the firewall and add these rules. They're checked lowest number first, and the first match wins.

A dash means leave the field empty, which means "any". Status is **Enabled** on every rule.

| Priority | Mode | Protocol | Source IP | Source port | Destination port | TCP status | What it's for |
|---|---|---|---|---|---|---|---|
| 0 | Accept | TCP | your address, e.g. `203.0.113.45/32` | – | `22` | – | SSH from you only |
| 1 | Accept | TCP | – | – | – | established | replies to connections the server opened |
| 2 | Accept | UDP | – | – | – | – | DNS and clock replies (nothing listens on UDP) |
| 3 | Accept | ICMP | – | – | – | – | ping, used by OVHcloud's monitoring |
| 4 | Accept | TCP | `173.245.48.0/20` | – | – | – | Cloudflare |
| 5 | Accept | TCP | `103.21.244.0/22` | – | – | – | Cloudflare |
| 6 | Accept | TCP | `103.22.200.0/22` | – | – | – | Cloudflare |
| 7 | Accept | TCP | `103.31.4.0/22` | – | – | – | Cloudflare |
| 8 | Accept | TCP | `141.101.64.0/18` | – | – | – | Cloudflare |
| 9 | Accept | TCP | `108.162.192.0/18` | – | – | – | Cloudflare |
| 10 | Accept | TCP | `190.93.240.0/20` | – | – | – | Cloudflare |
| 11 | Accept | TCP | `188.114.96.0/20` | – | – | – | Cloudflare |
| 12 | Accept | TCP | `197.234.240.0/22` | – | – | – | Cloudflare |
| 13 | Accept | TCP | `198.41.128.0/17` | – | – | – | Cloudflare |
| 14 | Accept | TCP | `162.158.0.0/15` | – | – | – | Cloudflare |
| 15 | Accept | TCP | `104.16.0.0/13` | – | – | – | Cloudflare |
| 16 | Accept | TCP | `104.24.0.0/14` | – | – | – | Cloudflare |
| 17 | Accept | TCP | `172.64.0.0/13` | – | – | – | Cloudflare |
| 18 | Accept | TCP | `131.0.72.0/22` | – | – | – | Cloudflare |
| 19 | Deny | IPv4 | – | – | – | – | everything else |

- **Check the Cloudflare ranges first:** compare rules 4 to 18 with https://www.cloudflare.com/ips/. It also has to match `trusted_proxies` in `deploy/Caddyfile`, so if Cloudflare's page differs, update both.
- **Why the ports are empty:** there isn't room for separate 80 and 443 rules. That's safe, because Docker publishes only 80 and 443, and the database and API have no published ports.

4. **Turn the firewall on** (Enabled). Rules do nothing while it's off, and changes can take a minute or two to apply.
5. **Test it:** open a **new** terminal and run `ssh inrotation`. Keep your current session open until that works.

## 4. Secure SSH and install Docker
On the server (`ssh inrotation`):

1. **Turn off password sign-in, and SSH over IPv6:**
   - Edit the file with `sudo nano /etc/ssh/sshd_config.d/50-hardening.conf` and make it contain:
     ```
     PasswordAuthentication no
     PermitRootLogin no
     AddressFamily inet
     ```
     `AddressFamily inet` keeps SSH on IPv4, where the firewall covers it.
   - Run `sudo systemctl reload ssh`.
   - Check from a new terminal that `ssh inrotation` still works.
   - Give `ubuntu` a password with `sudo passwd ubuntu` and keep it in your password manager. It can't be used over SSH, but the KVM console needs it if you ever lose your key (see "Locked out").
2. **Updates:** `sudo apt update && sudo apt upgrade -y`. If it says a restart is needed, run `sudo reboot` and reconnect after a minute. Ubuntu installs security updates by itself after that.
3. **Docker:**
   ```
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker ubuntu
   ```
   Then sign out and back in, so `docker` works without `sudo`. Check with `docker run --rm hello-world`.
4. **The site stays on IPv4.** `deploy/.env` (section 7) publishes ports 80 and 443 on IPv4 only (`HTTP_PORT=0.0.0.0:80`, `HTTPS_PORT=0.0.0.0:443`). Leave those lines as they are. Without them, the site would also be open on the VPS's IPv6 address, which the Edge firewall doesn't cover.
5. **Folders.** The containers run as uid 10001, so that user needs to own the folders they write to:
   ```
   sudo mkdir -p /srv/inrotation/{app,data,covers,avatars,backups,certs,releases}
   sudo chown -R 10001:10001 /srv/inrotation/{covers,avatars,backups}
   sudo chown -R ubuntu /srv/inrotation/{app,data,certs,releases}
   ```

## 5. Cloudflare
1. **Add the domain** to Cloudflare, then switch its nameservers at your registrar to the two Cloudflare gives you.
2. **DNS:** add an `A` record for the site's name pointing at the VPS's IPv4 address, with the proxy on (orange cloud). Don't add an `AAAA` (IPv6) record.
3. **SSL/TLS > Overview:** choose **Full (strict)**. Under Edge Certificates, turn on **Always Use HTTPS**.
4. **SSL/TLS > Origin Server > Create Certificate,** for the site's name. Save both parts on the server:
   - The certificate goes in `/srv/inrotation/certs/origin.pem`.
   - The private key goes in `/srv/inrotation/certs/origin-key.pem`.
   - Make the key readable only by you: `chmod 600 /srv/inrotation/certs/origin-key.pem`. Caddy reads it as root inside its container.

   For example, run `nano /srv/inrotation/certs/origin.pem` on the server, paste, then save with Ctrl+O, Enter and Ctrl+X.
5. **Caching:** add a **Cache Rule** for `/api/covers/*` (respect origin headers, which say 30 days), so covers come from Cloudflare's edge. Optionally turn on HSTS.

## 6. The code
There's no git repository yet, so copy the code from your Mac (repo root):
```
rsync -az --delete --exclude node_modules --exclude .venv --exclude __pycache__ --exclude '*.egg-info' \
  --exclude /data --exclude '*.duckdb' --exclude dist --exclude .env ./ inrotation:/srv/inrotation/app/
```
Run that again whenever the code changes. `--exclude .env` does two jobs:
- It keeps your local `backend/.env` off the server.
- It stops `--delete` from removing the server's own `deploy/.env`.

## 7. Settings
On the server:
```
cd /srv/inrotation/app
cp deploy/.env.example deploy/.env
nano deploy/.env
```
Fill in:
- **`SITE_ADDRESS`:** the domain.
- **`INROTATION_SECRET` and `POSTGRES_PASSWORD`:** make each one with `openssl rand -hex 32`.
- **`GEMINI_API_KEY`:** your key from the billed Google Cloud project.

Leave `HTTP_PORT` and `HTTPS_PORT` as they are (section 4, step 4).

## 8. Data
The data goes up as a versioned bundle (model, catalog, Album Map and a manifest with checksums).
1. **Build the bundle** on your Mac (repo root). It takes about a minute and writes `dist/releases/inrotation-data-<version>.tar.gz`, about 565 MB:
   ```
   python -m ingest.release
   ```
2. **Copy the bundle and the covers** to the server. The covers folder belongs to the containers' user (uid 10001), so first lend it to `ubuntu` **on the server**:
   ```
   sudo chown -R ubuntu /srv/inrotation/covers
   ```
   Then, **on your Mac**:
   ```
   scp dist/releases/inrotation-data-<version>.tar.gz inrotation:/srv/inrotation/releases/
   rsync -az data/covers/ inrotation:/srv/inrotation/covers/
   ```
3. **Install it.** On the server, give the covers back to the containers' user, then install the bundle from `/srv/inrotation/app`:
   ```
   sudo chown -R 10001:10001 /srv/inrotation/covers
   deploy/install-data.sh /srv/inrotation/releases/inrotation-data-<version>.tar.gz
   ```
   It checks every file against the manifest and points `/srv/inrotation/data/current` at the new version.

## 9. Start
Install the data first (section 8, step 3). `ls /srv/inrotation/data/current/` should list `catalog.db`. Then, from `/srv/inrotation/app`:
```
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml ps
```
- `migrate` runs the database migrations, then exits with 0.
- `api` turns healthy after about 10 s, and then `web` starts.
- The first build takes several minutes.

## 10. Check it
1. `https://<domain>/api/health` answers `{"status":"ok"}`.
2. `https://<domain>/` opens the home page.
3. Browse, rate 5 albums and open For You. Covers load. Ask answers if `GEMINI_API_KEY` is set.
4. Cloudflare can't be skipped. From your Mac, `curl -m 10 -k https://<VPS IPv4 address>/` should time out, because only Cloudflare may reach port 443. If it answers, the firewall isn't enabled or rule 19 is missing.
5. Run the nightly jobs once:
   ```
   docker compose -f deploy/compose.yaml exec jobs inrotation-jobs --now
   ```
   It writes `db-<time>.dump` and `avatars-<time>.tar.gz` to `/srv/inrotation/backups`.

## Day to day
- **Logs:** `docker compose -f deploy/compose.yaml logs -f api` (or `web`, `jobs`).
- **Contact messages:** `docker compose -f deploy/compose.yaml exec api python -m app.feedback`.
- **New code:**
  1. To keep a way back, first run `docker tag inrotation-api:latest inrotation-api:previous`, and the same for `inrotation-web`.
  2. Run the rsync from section 6 again.
  3. Run `docker compose -f deploy/compose.yaml up -d --build`. Migrations run by themselves.
- **New data** (after rebuilding the model, catalog or map):
  1. `python -m ingest.release` on your Mac, then copy the bundle up.
  2. Run `deploy/install-data.sh <bundle>`. It restarts the API and waits for it. If the API isn't healthy within about three minutes, it switches back by itself.
  3. The newest 3 versions stay installed. `deploy/install-data.sh --list` shows them, and `--use <version>` switches.
- **Backups:**
  - **Schedule:** they run nightly at 03:30 UTC (`JOBS_AT`) and are kept for 14 days (`BACKUP_DAYS`).
  - **Copy them off the server** now and then, because a backup on the same disk doesn't survive losing the VPS: `rsync -az inrotation:/srv/inrotation/backups/ ~/inrotation-backups/`. OVHcloud's paid automated backup option for the VPS is a further safety net.
  - **Restore the database:** `docker compose -f deploy/compose.yaml exec -T db pg_restore --clean --if-exists -U in_rotation -d in_rotation < /srv/inrotation/backups/db-<time>.dump`.
  - **Restore profile pictures:** `sudo tar -xzf /srv/inrotation/backups/avatars-<time>.tar.gz -C /srv/inrotation/avatars`.
- **Old anonymous users** are deleted by the nightly job: empty and unseen for 7 days, or unseen for a year (ADR 0024).
- **Cloudflare's address ranges** are written in two places: the Edge Network Firewall rules and `trusted_proxies` in `deploy/Caddyfile`. If Cloudflare publishes new ones, update both.

## Locked out
- **Your home address changed** (SSH times out): get the new one with `curl -4 ifconfig.me`. Then open the Edge Network Firewall page (section 3) and change rule 0's source to it.
- **You lost the private key:**
  1. On the VPS page in the Control Panel, open the **KVM** console. It works without SSH or the firewall.
  2. Sign in there as `ubuntu`, with the password from section 4. If you never set one, use the VPS page's **Rescue** mode instead.
  3. Add a new public key to `/home/ubuntu/.ssh/authorized_keys`.

## Before it goes up
The site has no password in front of it, so it's public from the first start. Settle the licensing first: the listening dataset's terms and the cover art. Consider a free uptime monitor on `/api/health`.

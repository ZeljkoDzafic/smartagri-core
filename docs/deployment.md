# Public deployment of the web app

The web app is local and single-user by default (`SMARTAGRI_ACCOUNTS=off`). This guide puts it on a public host
with optional accounts. The example hostname is `app.smartagri.rs.ba`; replace it with your own. Nothing here
changes evaluation runs: they never go through the web app.

The shape is: a container (or a Python process) listening on `127.0.0.1:8100`, a reverse proxy in front of it that
terminates TLS on port 443, a volume for the database, and a backup job.

## 1. Settings

Create `/srv/smartagri/.env` (never commit it; readable only by root and the service):

```bash
SMARTAGRI_ACCOUNTS=optional
SMARTAGRI_PUBLIC_URL=https://app.smartagri.rs.ba
# Administrators of the web settings. Without SMTP leave this empty and promote the owner on the server (section 2, first
# run): an address cannot be proven without email, so listing it grants nothing. With SMTP, list the owner's address (comma
# separated); the owner becomes an administrator by confirming the mailbox. See docs/settings.md.
SMARTAGRI_ADMINS=you@example.org
# Anonymous (not saved) parcels are deleted after this many hours without activity (default 24).
SMARTAGRI_ANON_TTL_HOURS=24
# Addresses of YOUR reverse proxy, exactly as the app sees its connections (see section 3). Only a connection from one of
# them may say, in X-Forwarded-For, who the client is. Never "*" and never a range that clients can reach: a client could then
# choose its own address and walk around every per-address limit. Empty (the default) trusts nobody: all visitors are
# counted under the proxy's address, which is safe but shared.
SMARTAGRI_TRUSTED_PROXIES=127.0.0.1
# Largest request body in bytes (default 262144). A request over it gets 413 before it is read.
SMARTAGRI_MAX_BODY_BYTES=262144
# Optional: email confirmation and password reset (all three of host, sender and public URL are needed).
SMARTAGRI_SMTP_HOST=smtp.example.org
SMARTAGRI_SMTP_PORT=587
SMARTAGRI_SMTP_TLS=starttls
SMARTAGRI_SMTP_USER=
SMARTAGRI_SMTP_PASSWORD=
SMARTAGRI_SMTP_FROM=SmartAgri <no-reply@example.org>
# Optional services (see .env.example): LLM_PROVIDER, CDSE_CLIENT_ID / CDSE_CLIENT_SECRET, DATABASE_URL, ...
```

`SMARTAGRI_PUBLIC_URL` is the address users type. It builds the links in emails (never the request's Host header),
it is an allowed Origin of state-changing requests, and with `https` it makes every cookie `Secure`.

Without SMTP, accounts work as soon as they are created, and there is no password reset: a user who forgets the
password has to create a new account. With SMTP, a new account must confirm its address before the first sign-in.

## 2. Container

The `Dockerfile` at the repository root builds the web app with SQLite in `/data` and `SMARTAGRI_ACCOUNTS=optional`.
It runs as an unprivileged user.

```bash
docker build -t smartagri-core .
docker volume create smartagri-data
docker run -d --name smartagri --restart unless-stopped \
  --env-file /srv/smartagri/.env \
  -v smartagri-data:/data \
  -p 127.0.0.1:8100:8100 \
  smartagri-core
curl -s http://127.0.0.1:8100/api/health
```

Publish the port on `127.0.0.1` only: the proxy is the only way in. Schema migrations run at start-up. For
PostgreSQL instead of SQLite, set `DATABASE_URL=postgresql://...` (the image includes the driver).

**The proxy's address inside the container.** The app sees a connection from the host's proxy as coming from the Docker
bridge's gateway, not from `127.0.0.1`. Put a network with a fixed subnet under the container, so the address is known:

```bash
docker network create --subnet 172.30.0.0/24 smartagri-net
# in the run command above add:  --network smartagri-net
# and in /srv/smartagri/.env:    SMARTAGRI_TRUSTED_PROXIES=172.30.0.1
```

`172.30.0.1` is the gateway of that network (check with `docker network inspect smartagri-net`). This guide's own tests run
the server and a proxy-style client on one host and do not run Docker; check it on your host: sign in with a wrong password
from two different machines and see that they are counted separately (a `429` on one does not follow the other). If the
address you trust is wrong, the app does not break: every visitor is counted under the proxy's address, so one visitor can
use up the limit of all (a denial of service, not a way around the limits). The image sets no trusted proxy, so a container
started without `SMARTAGRI_TRUSTED_PROXIES` is safe by default.

### First run on the public host (example: `app.smartagri.rs.ba`)

1. Create `/srv/smartagri/.env` as in section 1. Without SMTP: `SMARTAGRI_ADMINS` empty (or absent). With SMTP: the owner's
   address in `SMARTAGRI_ADMINS`.
2. Start the container and the proxy (sections 2 and 3). The first visit creates nothing special: until an administrator
   exists, every visitor is an ordinary user or anonymous.
3. **Promote the owner on the server**, before announcing the address:

   ```bash
   docker exec -it smartagri python -m smartagri.research_api --make-admin owner@example.org
   ```

   It asks for a password (twice). The account is created if it does not exist, and marked as confirmed by the operator.
   With SMTP the owner may instead sign up in the app and open the link in the mail (it sets the password); the command
   then only has to be run if the address is not listed.
4. Sign in as the owner: the Settings page shows the **Admin** tab. The promotion is in the audit log (level
   `admin_role`).
5. If someone signed up with the owner's address before step 3, nothing is lost: `--make-admin` takes the account over (new
   password, the old one stops working, its sessions end). Without SMTP such a sign-up is refused for an address listed in
   `SMARTAGRI_ADMINS` anyway. If the owner loses the password and the server has no email, run the command again with
   `--reset-password`. `--revoke-admin EMAIL` removes the role.
6. Check `GET /api/health` and one anonymous parcel, then announce the address.

Without Docker: `pip install -c requirements.lock -e ".[api,pg]"` in `backend/`, then run
`python -m smartagri.research_api --host 127.0.0.1 --port 8100` under systemd with the same environment file.

## 3. Reverse proxy and TLS

Caddy obtains and renews the certificate by itself and forwards the client address and scheme. Limit the body size too:

```caddyfile
app.smartagri.rs.ba {
    encode gzip
    request_body {
        max_size 256KB
    }
    reverse_proxy 127.0.0.1:8100
    header Strict-Transport-Security "max-age=31536000"
}
```

Caddy sets `X-Forwarded-For` to the address of the connection that reached it unless you list `trusted_proxies` in its global
options (do not, unless Caddy itself sits behind another proxy). This guide's tests did not run Caddy; check that the
address the app sees is the visitor's, as described in section 2.

With nginx (certificate from certbot), keep the `Host` header and **replace** the forwarded address with the one nginx saw
(`$remote_addr`), never append to what the client sent:

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name app.smartagri.rs.ba;
    ssl_certificate     /etc/letsencrypt/live/app.smartagri.rs.ba/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.smartagri.rs.ba/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 256k;
    location / {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
server { listen 80; server_name app.smartagri.rs.ba; return 301 https://$host$request_uri; }
```

How the address is decided: the app (not uvicorn) reads `X-Forwarded-For`, and only from a connection whose address is in
`SMARTAGRI_TRUSTED_PROXIES`. It skips every entry that is itself a trusted proxy and takes the next one from the right,
so even a proxy that appends instead of replacing (nginx's `$proxy_add_x_forwarded_for`) gives the address the proxy saw,
not what the client wrote. `python -m smartagri.research_api` therefore starts uvicorn with its own proxy handling off;
`FORWARDED_ALLOW_IPS=*`, which earlier versions of this guide advised, made uvicorn take the **leftmost** entry, an address
the client chose, and let a client walk around the per-address limits (sign-in, sign-up, reset, settings writes). The scheme
(`X-Forwarded-Proto`) is taken from a trusted proxy only. If you start the app with another server, switch its proxy
handling off or give it the same list.

## 4. Cookies, Origin and CORS

- Cookies are **host-only**: they carry no `Domain` attribute, so they are sent to `app.smartagri.rs.ba` and to no
  other subdomain. Do not add `Domain=.smartagri.rs.ba` in the proxy: the presentation site at `smartagri.rs.ba` must
  never receive session cookies.
- All cookies are `HttpOnly` (except `sa_csrf`, which the page must read), `SameSite=Lax`, and `Secure` on https.
  `sa_browser`, which identifies an anonymous visitor's temporary work, is a session cookie (no expiry date).
- The web app is served by the same origin as its API, so no CORS headers are sent and none are needed. Do not add
  `Access-Control-Allow-Origin` in the proxy. Browsers on other sites cannot read the API, and state-changing requests
  from them are refused: a request must carry the `X-CSRF-Token` header that matches the `sa_csrf` cookie, and its
  `Origin`, when present, must be `https://app.smartagri.rs.ba` (`SMARTAGRI_PUBLIC_URL`) or the request's own host.
- The blind rating endpoints (`/api/eval/`) are outside accounts, cookies and these checks. A public server is not
  the place for blind rating; run it locally.

## 5. Limits that protect sign-in

Every sign-in, sign-up, reset and confirmation request is counted per client address, and sign-in and reset are also
counted per email address, in fixed windows stored in the database (so several processes agree). Over the limit the
server answers `429` with `Retry-After`. Sign-in allows 10 attempts per email in 15 minutes. If many users share one
address (a school or an office behind NAT), raise the per-address limits with `SMARTAGRI_AUTH_RATE_FACTOR`.

## 5a. Request limits and response headers

- A request body over `SMARTAGRI_MAX_BODY_BYTES` (default 256 KiB) is refused with `413` before it is read, with or without
  a declared length. A JSON body nested deeper than 32 levels, or containing `NaN` or `Infinity`, gets `400`. A parcel
  polygon has at most 500 positions (the check for self-crossing is quadratic); a parcel name at most 120 characters, notes
  and a question at most 2000. Malformed input (a number where text is expected, a date that is not a date, a growth
  stage outside 0-99) is answered `400` with a message, never `500`, and nothing is stored.
- Every response carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
  `X-Frame-Options: DENY` and a `Content-Security-Policy` that lets the page load only its own files, plus map tiles
  from the host of `SMARTAGRI_TILE_URL` (default `tile.openstreetmap.org`), with `frame-ancestors 'none'`. The interactive
  API documentation at `/docs` loads its page from a content network and carries no policy. A browser that was told a
  different tile address in its own settings sheet can only show tiles from the configured host.
- Do not add a laxer `Content-Security-Policy` in the proxy: a second header only narrows the first.

## 6. Backups

The database holds accounts, parcels and conversations. Back it up daily and keep copies off the host.

SQLite (online copy with the backup API; safe while the app runs):

```bash
docker exec smartagri python -c "import sqlite3; s = sqlite3.connect('/data/smartagri.sqlite'); \
d = sqlite3.connect('/data/backup.sqlite'); s.backup(d); d.close()"
docker cp smartagri:/data/backup.sqlite /srv/backups/smartagri-$(date +%F).sqlite
```

PostgreSQL: `pg_dump --format=custom "$DATABASE_URL" > /srv/backups/smartagri-$(date +%F).dump`.

Encrypt copies that leave the host, keep them for a fixed period (for example 30 days) and say so in your privacy
notice: a deleted account stays in older backups until they expire. Test a restore now and then: stop the container,
copy a backup to `/data/smartagri.sqlite` in the volume, start it, and check `/api/health` and a sign-in.

## 7. Operating

- Update: pull, rebuild the image, `docker rm -f smartagri`, run it again with the same volume.
- Parcels created while accounts were off are hidden until assigned:
  `docker exec smartagri python -m smartagri.research_api --assign-unowned you@example.org`.
- Logs never contain passwords or tokens; email-sending failures are logged without addresses.
- Promote or demote an administrator: `python -m smartagri.research_api --make-admin EMAIL` and `--revoke-admin EMAIL`
  (section 2, first run). Both are in the audit log of the settings.
- Anonymous parcels are temporary. They and their conversations are deleted after `SMARTAGRI_ANON_TTL_HOURS`
  (default 24) without activity: lazily by the running app (at most every 10 minutes), and on demand with
  `docker exec smartagri python -m smartagri.research_api --purge-anonymous` (for example from a daily cron job).
  Saved (account) parcels and parcels from before accounts were turned on are never purged.

## 8. Not built yet (open items)

These are known gaps, written down so that nobody assumes they exist. The limits above protect the app from large and
malformed requests and the sign-in endpoints from guessing; they do not yet bound what a visitor makes the server spend:

- **Outbound provider calls.** Refreshing a parcel's profile calls the weather provider and, when configured, the
  Sentinel-2 provider (a new access token on every call). An anonymous visitor can trigger these repeatedly and use up the
  operator's quota of those services. There is no per-owner minimum interval and no daily quota yet.
- **Language-model spend.** With `LLM_PROVIDER` set, the free conversation (`/ai-chat`) sends every message (up to 2000
  characters) to the provider, with no per-owner or daily limit. Leave `LLM_PROVIDER=template` (the image default) on a
  public host, or put a spending limit on the provider's side, until a quota exists.
- **Parcels per owner and per address** are not limited; anonymous parcels are purged after `SMARTAGRI_ANON_TTL_HOURS`.
- The blind rating endpoints (`/api/eval/`) are still reachable (section 4); run blind rating locally.

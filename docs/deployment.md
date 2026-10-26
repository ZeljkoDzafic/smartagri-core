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
# The proxy runs on the same host and the container port is published on 127.0.0.1 only, so the forwarded client
# address can be trusted. Without this, every visitor shares the proxy's address and the per-address rate limits.
FORWARDED_ALLOW_IPS=*
# Optional: email confirmation and password reset (all three of host, sender and public URL are needed).
SMARTAGRI_SMTP_HOST=smtp.example.org
SMARTAGRI_SMTP_PORT=587
SMARTAGRI_SMTP_TLS=starttls
SMARTAGRI_SMTP_USER=
SMARTAGRI_SMTP_PASSWORD=
SMARTAGRI_SMTP_FROM=SmartAgri <no-reply@smartagri.rs.ba>
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

Without Docker: `pip install -c requirements.lock -e ".[api,pg]"` in `backend/`, then run
`python -m smartagri.research_api --host 127.0.0.1 --port 8100` under systemd with the same environment file.

## 3. Reverse proxy and TLS

Caddy obtains and renews the certificate by itself and forwards the client address and scheme:

```caddyfile
app.smartagri.rs.ba {
    encode gzip
    reverse_proxy 127.0.0.1:8100
    header Strict-Transport-Security "max-age=31536000"
}
```

With nginx (certificate from certbot), keep the `Host` header and send the forwarded headers:

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name app.smartagri.rs.ba;
    ssl_certificate     /etc/letsencrypt/live/app.smartagri.rs.ba/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.smartagri.rs.ba/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 2m;
    location / {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
server { listen 80; server_name app.smartagri.rs.ba; return 301 https://$host$request_uri; }
```

## 4. Cookies, Origin and CORS

- Cookies are **host-only**: they carry no `Domain` attribute, so they are sent to `app.smartagri.rs.ba` and to no
  other subdomain. Do not add `Domain=.smartagri.rs.ba` in the proxy: the presentation site at `smartagri.rs.ba` must
  never receive session cookies.
- All cookies are `HttpOnly` (except `sa_csrf`, which the page must read), `SameSite=Lax`, and `Secure` on https.
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
- Anonymous parcels are kept until the operator removes them; there is no automatic expiry yet.

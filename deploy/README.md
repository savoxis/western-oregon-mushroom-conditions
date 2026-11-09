# Deployment

Everything here uses placeholders. Real values live only on the servers, in files readable by root and the build user.

## VPS (primary)

1. Copy `scout/` to `/opt/mushroom-scout/` and `builder/` to `/opt/shrooms/` (keep `omshim/` and `tests/` inside it). Copy `site/` to `/opt/shrooms/site/`.
2. Create an unprivileged user (for example `mushroom`) that owns `/opt/shrooms/{data,cache,site/data}` and `/opt/mushroom-scout/cache`.
3. Cron (`/etc/cron.d/shrooms-build`):

   ```
   20 * * * * mushroom /usr/bin/python3 -B /opt/shrooms/shrooms_build.py auto >> /var/log/shrooms-build.log 2>&1
   ```

   The first runs backfill ten years of history within the free Open-Meteo archive limits (capped at 4,500 estimated calls per UTC day so the nightly build always has room), then the nightly build runs once a day after 6 am Pacific.
4. Optional config (all optional; the site works without them):

   `/etc/shrooms-openmeteo.env` (root:mushroom, 640)
   ```
   OPENMETEO_API_KEY=<commercial key>
   # 1 only on the API Professional plan (Historical Weather API); 0 keeps history calls on the free host
   OPENMETEO_ARCHIVE_CUSTOMER=0
   ```

   `/etc/shrooms/gemini.json` (root:mushroom, 640): `{"api_key": "<key>", "model": "<model name>"}` for the nightly brief.

   `/etc/shrooms/build.json` (root:mushroom, 640): `{"kuma": {"base": "https://<uptime-kuma>/api/push", "token": "<push token>"}}` for a build heartbeat.
5. Web server: any static server. The Caddy site block used in production:

   ```
   shrooms.example.org {
       root * /srv/shrooms                     # /opt/shrooms/site mounted read-only
       encode zstd gzip
       header {
           Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://inaturalist-open-data.s3.amazonaws.com https://basemap.nationalmap.gov https://gis.blm.gov https://tile.openstreetmap.org https://*.tile.openstreetmap.org; connect-src 'self' https://api.gbif.org; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
           X-Content-Type-Options nosniff
           Referrer-Policy strict-origin-when-cross-origin
           X-Frame-Options DENY
           Permissions-Policy "geolocation=(), camera=(), microphone=()"
           Strict-Transport-Security "max-age=31536000"
       }
       @data path /data/*
       header @data Cache-Control "public, max-age=300, must-revalidate"
       @static path /vendor/* /favicon.svg
       header @static Cache-Control "public, max-age=604800"
       @shell path / /index.html /stats.html /sources.html /app.js /calcs.js /dash.js /style.css /theme.css /oregon.json
       header @shell Cache-Control "no-cache"
       file_server
   }
   ```

   If the Caddyfile is a single-file bind mount, restart the container after editing it (`sed -i` replaces the inode, so a reload keeps the old file).

## Home fallback (optional)

`deploy/failover/shrooms-agent.sh` runs every minute on a home server. It pulls the built site from the VPS over SSH with a read-only forced-command key (`rrsync -ro`), checks it is identical and fresh, and flips the site's DNS A record to the home IP if the VPS has been down for 5 minutes (back after 10 minutes healthy). `deploy/home-nginx/` mirrors the Caddy headers for an nginx container behind a reverse proxy. `deploy/failover/shrooms-home-probe.sh` runs on the VPS and checks the home copy from the internet.

Agent config (`shrooms.env`, root only): `CF_TOKEN` (a Cloudflare token limited to DNS edit on the one zone), `ZONE_ID`, `RECORD_NAME`, `VPS_IP`, `HOME_DDNS_HOST`, `NPM_IP`, `NPM_PORT`, `HOME_DIRECT`, `WWW`, `KUMA_BASE`, `TOKEN_STATE`, `TOKEN_SYNC`, `ENABLE_FLIP` (0 = observe only). Probe config (`/etc/shrooms-failover.env`): `HOME_DDNS_HOST`, `KUMA_BASE`, `TOKEN_REACH`.

The sync key on the VPS is restricted in `authorized_keys` with `restrict,command="/usr/bin/rrsync -ro /opt/shrooms/site"`.

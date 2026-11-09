# Deploying usc-flask

How the Unified Social Club backend goes live on the OCS server, so the live site
(https://unified-social-club-csp.github.io/usc-pages/) can sign members in, save
progress, and load Jeopardy boards. Tracked in issue #1.

## What we need from Mr. Mortensen
1. A subdomain on opencodingsociety.com. We're asking for `usc.opencodingsociety.com`.
2. A DNS record pointing it at the OCS server, the same way `flask.opencodingsociety.com` points there.
3. Port **8588** on the server for our container (OCS Flask uses 8587).
4. The usual OCS deployment access (or a deployment session with him) to run the steps below.

## Files
| File | What it is |
|---|---|
| `deploy/docker-compose.yml` | Only our web container (`usc_flask`) on 8588, built from the stock OCS `Dockerfile` |
| `deploy/usc.env.example` | Production settings to copy to `deploy/usc.env` on the server (never committed) |
| `deploy/nginx_usc_flask.conf` | nginx reverse proxy for the subdomain, same pattern as `nginx_flask_8587.conf` |

## Steps on the server
```bash
git clone https://github.com/Unified-Social-Club-CSP/usc-flask.git && cd usc-flask/deploy
cp usc.env.example usc.env      # fill in SECRET_KEY, passwords
docker compose up -d --build
docker exec -e FORCE_YES=true -e ALLOW_NO_BACKUP=true usc_flask python scripts/db_init.py   # first time only
curl -s localhost:8588/api/usc/jeopardy/boards    # expect the Club Life board
sudo cp nginx_usc_flask.conf /etc/nginx/sites-available/ && sudo ln -s /etc/nginx/sites-available/nginx_usc_flask.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d usc.opencodingsociety.com
```

Then in usc-pages, set the production `pythonURI` in `assets/js/api/config.js` to `https://usc.opencodingsociety.com`.

## Things we checked before asking
- **Cookie collision (must fix before going live).** In production, `api/user.py` sets the login cookie on `.opencodingsociety.com`. With the OCS default name `jwt_python_flask`, signing in to our site would overwrite a student's OCS login. `usc.env.example` sets `JWT_TOKEN_NAME=jwt_usc_flask` and `SESSION_COOKIE_NAME=sess_usc_flask`.
- **Default passwords.** Without `ADMIN_PASSWORD`/`DEFAULT_PASSWORD`, the starter accounts get the password `password`.
- **CORS.** `__init__.py` and the nginx file both allow `https://unified-social-club-csp.github.io`.
- **Third-party cookies.** Our site is on github.io and the API on opencodingsociety.com, so the login cookie is cross-site (`SameSite=None; Secure`). Chrome and Firefox allow it; Safari may block it. If that's a problem for club members on iPads, we can ask to serve the frontend from an opencodingsociety.com address too.
- **Load.** A Bingo or Trivia room is 10–20 phones polling about once a second; 3 gunicorn workers with 2 threads each should handle it, and we'll measure it before a club night.
- **Backups.** `instance/` is a volume, so the SQLite database survives rebuilds. We'll copy it off the server before each club night until there's a regular backup.

## Check after deploy
Sign in, answer the survey, play a Jeopardy game (it should appear under "Recent games"), and join a Bingo room from two devices, all on the live site. Paste the results in issue #1.

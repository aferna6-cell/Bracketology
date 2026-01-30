# Deployment Plan (Safe Checklist)

## 1) Pre-deploy checks

- [ ] Review `SECURITY.md` and confirm threat model assumptions match your environment.
- [ ] Run the CI checks locally (tests + static checks + dependency audit).
- [ ] Verify `requirements.txt` has pinned versions where appropriate.

## 2) Environment configuration

- [ ] Copy `.env.example` to `.env` and set `PORT` and `FLASK_DEBUG=0`.
- [ ] Ensure filesystem permissions protect the `data/` directory.
- [ ] Configure a reverse proxy (e.g., Nginx) for TLS and rate limiting.

## 3) Production server

- [ ] Use a production WSGI server (e.g., Gunicorn) behind the proxy:
  - Example: `gunicorn -w 4 -b 0.0.0.0:$PORT run:app`
- [ ] Configure process manager (systemd, supervisor, or container runtime).

## 4) Observability

- [ ] Centralize logs and monitor update failures or ESPN API outages.
- [ ] Track performance of `/api/update` and `/api/scoreboard`.

## 5) Rollback plan

- [ ] Keep the previous release packaged (or tag) for instant rollback.
- [ ] Backup the SQLite database before deploying new code.

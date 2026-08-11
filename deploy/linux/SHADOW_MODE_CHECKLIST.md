# Project Gwala Shadow-Mode Verification Checklist

Use this before enabling VPS timers and after the first market session.

## Before Enabling Timers

- [ ] VPS timezone intentionally set.
- [ ] Repository copied to `/opt/project-gwala`.
- [ ] Python 3.11 virtual environment created at `/opt/project-gwala/.venv-webull`.
- [ ] `requirements.txt` installed.
- [ ] `requirements-webull.txt` installed.
- [ ] `/etc/project-gwala/gwala.env` exists and is `chmod 600`.
- [ ] `GWALA_DEPLOYMENT_MODE=shadow`.
- [ ] `GWALA_DISABLE_BROKER_EXECUTION=true`.
- [ ] `GWALA_LIVE_TRADING_ENABLED=false`.
- [ ] Webull credentials are present only in the VPS environment file.
- [ ] `.webull_tokens/` is present only if intentionally transferred securely.
- [ ] `deploy/linux/preflight.py` passes.
- [ ] Dashboard host remains `127.0.0.1` unless protected by SSH tunnel or reverse proxy auth.

## First Shadow Session

- [ ] `systemctl is-active project-gwala-dashboard.service` reports `active`.
- [ ] `systemctl list-timers 'project-gwala-*'` shows the autonomous-paper,
      production-alert, opening-report, and EOD-report timers.
- [ ] Dashboard service starts without exposing broker controls publicly.
- [ ] Autonomous paper workflow writes status artifacts under `logs/`.
- [ ] Host runs `deploy/linux/write_host_systemd_health.py` before Dockerized
      heartbeat or production-alert checks.
- [ ] Docker container receives `GWALA_HOST_SYSTEMD_HEALTH_JSON` pointing to the
      mounted host health artifact.
- [ ] Production heartbeat uses the host-generated systemd health artifact in
      Docker, not `systemctl` inside the container.
- [ ] macOS notification path is disabled gracefully on Linux.
- [ ] Opening Executive Report archives locally.
- [ ] EOD Executive Report archives locally.
- [ ] No broker orders are placed.
- [ ] No Webull order endpoints are called.
- [ ] macOS production LaunchAgents remain running independently.

## After First Session

- [ ] Compare VPS `logs/executive_reports/` with macOS archive.
- [ ] Compare scanner row counts between systems.
- [ ] Compare heartbeat status between systems.
- [ ] Confirm no secrets appeared in service logs.
- [ ] Keep VPS in shadow mode until explicitly promoted.

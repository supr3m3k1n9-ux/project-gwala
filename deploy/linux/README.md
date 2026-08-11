# Project Gwala Ubuntu Shadow Deployment

This directory prepares Project Gwala to run on an Ubuntu VPS in parallel
shadow mode. It does not replace or disable the current macOS LaunchAgents.

## Architecture

- Project root: `/opt/project-gwala`
- Environment file: `/etc/project-gwala/gwala.env`
- Service logs: `/var/log/project-gwala`
- Scheduler: `systemd` services and timers
- Dashboard: Python `http.server` through `run_app.py`
- Trading posture: local paper-validation shadow mode only
- Host systemd health artifact: `/opt/project-gwala/logs/host_systemd_health.json`
- Runtime data: host evidence remains under `/srv/projects/gwala/data`; inside
  Docker it is mounted at `/app/runtime_data` so `/app/data` remains the Python
  source package.
- Docker security: root `compose.yaml` runs the Gwala service as UID/GID
  `1000:1000` with `security_opt: no-new-privileges:true`.

The Linux services and timers mirror the current macOS production roles:

- Dashboard runs as an always-on systemd service.
- Autonomous paper workflow runs each scheduled market-cycle decision with `--once`.
- Production alert checks run on the offset alert cadence.
- Opening Executive Report runs at `06:20`.
- EOD Executive Report checks run at `13:05`, `13:10`, `13:15`, `13:20`, and `13:30`.

Set the VPS timezone intentionally before enabling timers. If matching the
current LaunchAgent wall-clock schedule, use:

```bash
sudo timedatectl set-timezone America/Los_Angeles
```

## Future VPS Installation Steps

Run these on the Ubuntu VPS, not on the macOS production machine.

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip git
sudo mkdir -p /opt/project-gwala
sudo chown "$USER:$USER" /opt/project-gwala
```

Copy the repository to `/opt/project-gwala`, then:

```bash
cd /opt/project-gwala
python3.11 -m venv .venv-webull
.venv-webull/bin/pip install --upgrade pip
.venv-webull/bin/pip install -r requirements.txt
.venv-webull/bin/pip install -r requirements-webull.txt
sudo GWALA_PROJECT_ROOT=/opt/project-gwala deploy/linux/install_linux_shadow.sh
sudo editor /etc/project-gwala/gwala.env
.venv-webull/bin/python deploy/linux/preflight.py
```

Only after preflight passes:

```bash
sudo systemctl enable --now project-gwala-dashboard.service
sudo systemctl enable --now project-gwala-autonomous-paper.timer
sudo systemctl enable --now project-gwala-production-alert.timer
sudo systemctl enable --now project-gwala-opening-executive-report.timer
sudo systemctl enable --now project-gwala-eod-executive-report.timer
```

## Manual Shadow Commands

```bash
cd /opt/project-gwala
.venv-webull/bin/python run_app.py --host 127.0.0.1 --port 8765
.venv-webull/bin/python run_autonomous_paper_workflow.py --interval-minutes 5 --auto-confirm-paper-exits --once
.venv-webull/bin/python run_production_alert.py --output-dir logs --data-dir "${GWALA_DATA_DIR:-data}" --interval-minutes 5 --cooldown-minutes 30 --recheck-seconds 25 --outage-threshold-minutes 5 --down-confirmation-failures 2
.venv-webull/bin/python run_executive_report.py --report-type opening --output-dir logs --data-dir "${GWALA_DATA_DIR:-data}" --reports-dir logs/executive_reports --deliver
.venv-webull/bin/python run_executive_report.py --report-type eod --output-dir logs --data-dir "${GWALA_DATA_DIR:-data}" --reports-dir logs/executive_reports --deliver
```

## Docker Host Systemd Health

The Ubuntu host owns `systemd`; the Docker container does not. Do not mount the
host systemd or dbus socket into the container.

Before a Dockerized production heartbeat or production alert check, the host
wrapper should refresh the host health artifact:

```bash
cd /srv/projects/gwala
python3 deploy/linux/write_host_systemd_health.py --output logs/host_systemd_health.json
/srv/projects/gwala/run_in_docker.sh python run_production_alert.py --output-dir logs --data-dir /app/runtime_data --interval-minutes 5 --cooldown-minutes 30 --recheck-seconds 25 --outage-threshold-minutes 5 --down-confirmation-failures 2
```

Inside Docker, `run_production_heartbeat.py` reads
`GWALA_HOST_SYSTEMD_HEALTH_JSON` instead of calling `systemctl`. If the artifact
is missing or stale, heartbeat reports an explicit YELLOW unknown state. If the
host artifact reports an unhealthy Project Gwala service or timer, heartbeat
reports RED.

## Continuous Assurance

The continuous assurance runner coordinates existing read-only checks and
host-generated artifacts into durable runtime, premarket, EOD, and weekly
assurance artifacts. The application container must not require the Docker CLI
or host Docker socket. Refresh host Docker and host security health on the
Ubuntu host before containerized assurance checks:

```bash
cd /srv/projects/gwala
python3 deploy/linux/write_host_docker_health.py --output logs/host_docker_health.json
python3 deploy/linux/write_host_security_health.py --output logs/host_security_health.json
```

Then run assurance inside Docker:

```bash
/srv/projects/gwala/run_in_docker.sh python run_continuous_assurance.py --layer runtime
/srv/projects/gwala/run_in_docker.sh python run_continuous_assurance.py --layer premarket --run-linux-preflight
/srv/projects/gwala/run_in_docker.sh python run_continuous_assurance.py --layer eod
/srv/projects/gwala/run_in_docker.sh python run_continuous_assurance.py --layer weekly --run-tests
```

The proposed systemd cadence is documented for review in
`deploy/linux/CONTINUOUS_ASSURANCE.md`. Do not enable new assurance timers until
that schedule is reviewed on the VPS.

For Docker/Linux premarket checks, `/app/.env` is not expected. Secrets are
injected into the container process by the host Compose `env_file`, sourced from
`/srv/projects/gwala/config/gwala.env`. Premarket assurance verifies required
secret variable names inside the container without printing values. Host secret
file permissions and host security posture are verified by the read-only
`logs/host_security_health.json` artifact. If that artifact is missing or stale,
premarket assurance reports WATCH rather than a false missing `.env` warning.

## Safety Requirements

The VPS environment must keep:

```text
GWALA_DEPLOYMENT_MODE=shadow
GWALA_SHADOW_MODE=true
GWALA_DISABLE_BROKER_EXECUTION=true
GWALA_LIVE_TRADING_ENABLED=false
GWALA_BROKER_ORDER_EXECUTION_ENABLED=false
GWALA_REAL_MONEY_READY=false
```

This deployment layer does not add broker order placement, Webull execution, or
real-money trading.

## Rollback

```bash
cd /opt/project-gwala
sudo deploy/linux/rollback_linux_shadow.sh
```

Rollback removes the systemd services and timers. It preserves:

- `/etc/project-gwala/gwala.env`
- `/opt/project-gwala`
- `/var/log/project-gwala`

## Files Not To Commit

- `/etc/project-gwala/gwala.env`
- `.env`
- `.webull_tokens/`
- Gmail app passwords
- Webull credentials
- Polygon API keys

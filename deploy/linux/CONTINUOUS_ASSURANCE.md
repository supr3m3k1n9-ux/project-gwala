# Project Gwala Continuous Assurance

This is the proposed Linux/systemd assurance layer for Docker shadow mode. It is
control-plane only: it observes, verifies, classifies, reports, and recommends a
trigger. It must not change strategy logic, gates, risk policy, research
thresholds, broker behavior, trading execution, or capital state.

## Command

```bash
python3 deploy/linux/write_host_docker_health.py --output logs/host_docker_health.json
/srv/projects/gwala/run_in_docker.sh python run_continuous_assurance.py --layer runtime
/srv/projects/gwala/run_in_docker.sh python run_continuous_assurance.py --layer premarket --run-linux-preflight
/srv/projects/gwala/run_in_docker.sh python run_continuous_assurance.py --layer eod
/srv/projects/gwala/run_in_docker.sh python run_continuous_assurance.py --layer weekly --run-tests
```

Artifacts are written under:

```text
logs/assurance/
  runtime/runtime_smoke.json
  runtime/runtime_smoke.md
  premarket/premarket_assurance.json
  premarket/premarket_assurance.md
  eod/eod_evidence_integrity.json
  eod/eod_evidence_integrity.md
  weekly/weekly_deep_assurance.json
  weekly/weekly_deep_assurance.md
  assurance_state.json
  assurance_state.md
```

## Proposed Timers For Review

Do not enable these until they are reviewed on the VPS.

Runtime smoke:

```ini
[Timer]
OnCalendar=Mon..Fri *-*-* 06:00..13:45/5:00 America/Los_Angeles
Persistent=true
```

Premarket assurance:

```ini
[Timer]
OnCalendar=Mon..Fri *-*-* 06:10:00 America/Los_Angeles
Persistent=true
```

EOD evidence integrity:

```ini
[Timer]
OnCalendar=Mon..Fri *-*-* 13:40:00 America/Los_Angeles
Persistent=true
```

Weekly deep assurance:

```ini
[Timer]
OnCalendar=Sat *-*-* 09:00:00 America/Los_Angeles
Persistent=true
```

## Assurance Layers

Runtime smoke is lightweight and intended for market hours. It reuses the fresh
production heartbeat artifact, consumes a host-generated Docker health artifact
when running inside the application container, verifies writable persistent
paths, checks resource pressure, confirms dashboard localhost binding, confirms
this process is not pointed at a remote Docker endpoint, and verifies the
approved shadow-mode safety environment.

Premarket assurance is the readiness gate before a session. It compiles critical
modules with read-only `compile(source_text, filename, "exec")` syntax checks
that do not write `__pycache__` or `.pyc` files, reuses dashboard preflight,
optionally runs the Linux preflight, checks secret/token configuration, and can
run the focused safety suite when explicitly requested.

EOD evidence integrity decides whether the day is trustworthy for research
runway accounting. It reuses the Data Flow Sentinel, audits authoritative VWAP
and ORB ledgers for duplicates, checks timestamps, and checks for strategy
ledger contamination.

Weekly deep assurance is the heavier non-market audit. It compiles critical
modules, runs the read-only code auditor, reviews governance files, inventories
worktree changes, checks dependency pinning drift, audits live-capital safety
flag references, and can run the complete unittest suite when explicitly
requested.

## Status Model

GREEN means all material controls passed.

WATCH means there is uncertainty or non-critical degradation, but safe research
operation may continue after review.

RED means research integrity, safety, authentication, scheduling, evidence
validity, or live-capital safety is materially compromised.

Every RED report includes:

```text
red_component
red_reason
business_impact
research_impact
operator_action_required
engineering_trigger
affected_session
affected_strategy
recommended_next_action
```

## Resource Rules

Runtime smoke must stay lightweight during market hours.

Full tests, code-security scans, dependency drift review, and other heavy audits
belong outside market hours.

The assurance loop records duration for every layer so the VPS can detect if
audits are getting too expensive for the current server size.

## Host/Container Boundary

Inside the application container:

- data/log writability
- disk and memory visibility available to the process
- shadow safety environment
- dashboard localhost binding environment
- current process Docker endpoint environment

Host-generated artifacts:

- `logs/host_docker_health.json`
- `logs/host_systemd_health.json`
- `logs/host_security_health.json`

Existing application artifacts:

- `logs/production_heartbeat.json`

Missing or stale host Docker health is WATCH/unknown, not GREEN. A fresh
unhealthy host Docker artifact is RED. The application container must not mount
`/var/run/docker.sock` to satisfy assurance.

On Docker/Linux, `/app/.env` is not expected. Secrets are injected into the
container process by the host Compose `env_file`, with the host source expected
at `/srv/projects/gwala/config/gwala.env`. Inside the container, premarket
assurance verifies required secret variable names are present and non-placeholder
without printing values. Host file permission verification belongs in a
host-generated security artifact; missing host verification is WATCH, not a
false `.env missing` warning.

## Safety Boundary

The assurance runner is read-only. It does not import official paper trades,
place broker orders, run validation imports, trigger lifecycle changes, change
systemd state, or mutate strategy configuration.

The Linux/Docker shadow posture remains:

```text
GWALA_DEPLOYMENT_MODE=shadow
GWALA_SHADOW_MODE=true
GWALA_DISABLE_BROKER_EXECUTION=true
GWALA_LIVE_TRADING_ENABLED=false
GWALA_BROKER_ORDER_EXECUTION_ENABLED=false
GWALA_REAL_MONEY_READY=false
```

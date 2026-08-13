#!/usr/bin/env bash
set -euo pipefail

# Project Gwala pre-session acceptance runner.
#
# Intended sudoers grant after review:
# roy ALL=(root) NOPASSWD: /srv/projects/gwala/app/deploy/linux/run_presession_acceptance.sh
#
# Security boundary:
# - No arbitrary command, Docker, Python, or journal arguments are accepted.
# - All checks are fixed below.
# - Fixture/test output is isolated under logs/presession_acceptance.
# - Authoritative runtime data and broker/live state are never intentionally
#   mutated by this runner.

if [[ "${1:-}" == "--help" ]]; then
  cat <<'HELP'
Project Gwala pre-session acceptance runner.

Runs the fixed, production-safe acceptance suite only. No arbitrary arguments
or shell commands are accepted.
HELP
  exit 0
fi

if [[ "$#" -ne 0 ]]; then
  echo "ERROR: run_presession_acceptance.sh does not accept arguments." >&2
  exit 64
fi

umask 022
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

STACK_DIR="/srv/projects/gwala"
APP_DIR="$STACK_DIR/app"
COMPOSE_FILE="$STACK_DIR/compose.yaml"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RESULT_DIR="$STACK_DIR/logs/presession_acceptance/$RUN_ID"
CHECKS_TSV="$RESULT_DIR/checks.tsv"
STDOUT_LOG="$RESULT_DIR/command_output.log"

mkdir -p "$RESULT_DIR"
printf 'area\tstatus\treason\n' > "$CHECKS_TSV"
: > "$STDOUT_LOG"

export GWALA_APP_DIR="$APP_DIR"
export GWALA_STACK_DIR="$STACK_DIR"

record_check() {
  local area="$1"
  local status="$2"
  local reason="$3"
  reason="${reason//$'\t'/ }"
  reason="${reason//$'\n'/ }"
  printf '%s\t%s\t%s\n' "$area" "$status" "$reason" >> "$CHECKS_TSV"
}

run_fixed() {
  local area="$1"
  local timeout_seconds="$2"
  shift 2
  {
    printf '\n=== %s ===\n' "$area"
    printf 'command:'
    printf ' %q' "$@"
    printf '\n'
  } >> "$STDOUT_LOG"
  if timeout "$timeout_seconds" "$@" >> "$STDOUT_LOG" 2>&1; then
    record_check "$area" "PASS" "fixed command completed"
  else
    local code="$?"
    record_check "$area" "FAIL" "fixed command failed with rc=$code"
  fi
}

run_fixed_watch() {
  local area="$1"
  local timeout_seconds="$2"
  shift 2
  {
    printf '\n=== %s ===\n' "$area"
    printf 'command:'
    printf ' %q' "$@"
    printf '\n'
  } >> "$STDOUT_LOG"
  if timeout "$timeout_seconds" "$@" >> "$STDOUT_LOG" 2>&1; then
    record_check "$area" "PASS" "fixed command completed"
  else
    local code="$?"
    record_check "$area" "WATCH" "fixed diagnostic command returned rc=$code"
  fi
}

run_docker_unittest() {
  local area="$1"
  shift
  run_fixed "$area" 240 \
    docker compose -f "$COMPOSE_FILE" run --rm --no-deps gwala \
    python -m unittest "$@"
}

run_docker_python() {
  local area="$1"
  local snippet="$2"
  run_fixed "$area" 180 \
    docker compose -f "$COMPOSE_FILE" run --rm --no-deps gwala \
    python -c "$snippet"
}

run_vps_verifier() {
  local area="Production verifier"
  local tmp="$RESULT_DIR/vps_verifier.out"
  {
    printf '\n=== %s ===\n' "$area"
    printf 'command: %q %q %q %q %q %q %q\n' \
      /usr/bin/python3 "$APP_DIR/deploy/linux/verify_vps_production.py" \
      --app-dir "$APP_DIR" --stack-dir "$STACK_DIR"
  } >> "$STDOUT_LOG"
  if timeout 240 /usr/bin/python3 "$APP_DIR/deploy/linux/verify_vps_production.py" \
    --app-dir "$APP_DIR" --stack-dir "$STACK_DIR" > "$tmp" 2>&1
  then
    cat "$tmp" >> "$STDOUT_LOG"
    if grep -q "VPS PRODUCTION READINESS: PASS" "$tmp"; then
      record_check "$area" "PASS" "VPS production readiness PASS"
    elif grep -q "VPS PRODUCTION READINESS: WATCH" "$tmp"; then
      record_check "$area" "WATCH" "VPS production readiness WATCH"
    elif grep -q "VPS PRODUCTION READINESS: FAIL" "$tmp"; then
      record_check "$area" "FAIL" "VPS production readiness FAIL"
    else
      record_check "$area" "WATCH" "VPS verifier output did not include readiness status"
    fi
  else
    local code="$?"
    cat "$tmp" >> "$STDOUT_LOG" 2>/dev/null || true
    record_check "$area" "FAIL" "VPS verifier failed with rc=$code"
  fi
}

APP_SHA="$(git -C "$APP_DIR" rev-parse --short HEAD)"

run_vps_verifier

run_fixed "Source runtime boundary" 120 \
  /usr/bin/python3 "$APP_DIR/deploy/linux/verify_docker_runtime_boundary.py" \
  --compose-file "$COMPOSE_FILE" --app-dir "$APP_DIR" --stack-dir "$STACK_DIR"

run_fixed_watch "Docker capacity" 60 docker system df

run_fixed_watch "Project Gwala systemd timers" 60 \
  systemctl list-timers "project-gwala*" --all --no-pager

run_fixed_watch "Project Gwala systemd units" 60 \
  systemctl list-units "project-gwala*" --all --no-pager

for unit in \
  project-gwala-autonomous-paper.service \
  project-gwala-market-async-lane.service \
  project-gwala-production-alert.service \
  project-gwala-dashboard.service \
  project-gwala-opening-executive-report.service \
  project-gwala-eod-executive-report.service
do
  run_fixed_watch "Journal $unit" 60 journalctl -u "$unit" --since "24 hours ago" --no-pager -n 80
done

run_fixed "Clock session" 60 timedatectl
run_fixed_watch "Resource capacity df" 60 df -h
run_fixed_watch "Resource capacity inodes" 60 df -i
run_fixed_watch "Resource capacity memory" 60 free -h

run_docker_unittest "Data freshness severity fixtures" \
  tests.test_workflow_safety.DataFreshnessIntegrityAuditorTests

run_docker_unittest "Scheduler phase fixtures" \
  tests.test_workflow_safety.MarketCalendarTests.test_autonomous_supervisor_selects_premarket_check \
  tests.test_workflow_safety.MarketCalendarTests.test_autonomous_supervisor_selects_market_scan \
  tests.test_workflow_safety.MarketCalendarTests.test_autonomous_supervisor_selects_after_close_recap \
  tests.test_workflow_safety.MarketCalendarTests.test_after_close_recap_runs_evidence_maturity_first \
  tests.test_workflow_safety.MarketCalendarTests.test_after_close_maturity_refresh_does_not_call_append_collectors

run_docker_unittest "Candidate lifecycle preview fixtures" \
  tests.test_workflow_safety.MarketCalendarTests.test_candidate_window_ledger_persists_current_candle_candidate \
  tests.test_workflow_safety.MarketCalendarTests.test_candidate_window_ledger_preserves_first_paper_gate_ready_state \
  tests.test_workflow_safety.MarketCalendarTests.test_candidate_ledger_event_dispatch_triggers_contract_gate_for_new_a_tier_row \
  tests.test_workflow_safety.MarketCalendarTests.test_candidate_ledger_event_dispatch_retries_lifecycle_safety_blocks \
  tests.test_workflow_safety.MarketCalendarTests.test_candidate_ledger_event_dispatch_blocks_after_close_replay \
  tests.test_workflow_safety.MarketCalendarTests.test_options_contract_gate_uses_preserved_candidate_ledger_state_after_scanner_ages

run_docker_unittest "Open-position M5 fixtures" \
  tests.test_workflow_safety.PaperGuardrailTests.test_trading_critical_path_excludes_async_research_and_reporting \
  tests.test_workflow_safety.PaperGuardrailTests.test_invalid_open_validation_rows_do_not_trigger_m5_exit_priority \
  tests.test_workflow_safety.PaperGuardrailTests.test_valid_open_paper_trade_prioritizes_m5_exit_management

run_docker_unittest "Runtime path fixtures" \
  tests.test_runtime_paths.RuntimePathTests.test_docker_runtime_data_root_is_not_source_package_path \
  tests.test_runtime_paths.RuntimePathTests.test_refresh_audit_related_defaults_use_runtime_data_in_docker \
  tests.test_runtime_paths.RuntimePathTests.test_repository_compose_mounts_runtime_data_not_source_package \
  tests.test_runtime_paths.RuntimePathTests.test_linux_systemd_docker_services_use_runtime_data_mount

run_docker_unittest "Broker live safety fixtures" \
  tests.test_continuous_assurance.ContinuousAssuranceTests.test_safety_env_red_when_live_boundary_is_not_shadow \
  tests.test_workflow_safety.StateAndEndpointTests.test_system_state_marks_todays_scanner_non_actionable_after_close

run_docker_python "Premarket freshness audit fixture" \
  "from pathlib import Path; from run_data_freshness_audit import build_audit, write_audit; from run_production_heartbeat import parse_et_datetime; out=Path('/app/logs/presession_acceptance/$RUN_ID/premarket_freshness'); out.mkdir(parents=True, exist_ok=True); payload=build_audit(Path('/app/runtime_data'), parse_et_datetime('2026-08-14 09:20:00 EDT'), candle_dir=Path('/app/logs')); write_audit(payload, out); print(payload.get('status'), payload.get('session_evidence'))"

run_docker_python "Regular-session freshness audit fixture" \
  "from pathlib import Path; from run_data_freshness_audit import build_audit, write_audit; from run_production_heartbeat import parse_et_datetime; out=Path('/app/logs/presession_acceptance/$RUN_ID/regular_freshness'); out.mkdir(parents=True, exist_ok=True); payload=build_audit(Path('/app/runtime_data'), parse_et_datetime('2026-08-14 10:35:00 EDT'), candle_dir=Path('/app/logs')); write_audit(payload, out); print(payload.get('status'), payload.get('session_evidence'))"

run_docker_python "After-close freshness audit fixture" \
  "from pathlib import Path; from run_data_freshness_audit import build_audit, write_audit; from run_production_heartbeat import parse_et_datetime; out=Path('/app/logs/presession_acceptance/$RUN_ID/afterclose_freshness'); out.mkdir(parents=True, exist_ok=True); payload=build_audit(Path('/app/runtime_data'), parse_et_datetime('2026-08-14 16:10:00 EDT'), candle_dir=Path('/app/logs')); write_audit(payload, out); print(payload.get('status'), payload.get('session_evidence'))"

/usr/bin/python3 - "$CHECKS_TSV" "$RESULT_DIR" "$APP_SHA" <<'PY'
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

checks_path = Path(sys.argv[1])
result_dir = Path(sys.argv[2])
commit = sys.argv[3]

rows = list(csv.DictReader(checks_path.open(newline=""), delimiter="\t"))
areas = {
    "Trading Critical Path": ["Open-position M5 fixtures"],
    "Entry Timing Margin": ["Open-position M5 fixtures"],
    "Open-Position M5 Path": ["Open-position M5 fixtures"],
    "Webull": ["Production verifier"],
    "Runtime Paths": ["Runtime path fixtures", "Source runtime boundary"],
    "Scheduler": ["Scheduler phase fixtures", "Project Gwala systemd timers", "Project Gwala systemd units"],
    "Data Freshness": [
        "Data freshness severity fixtures",
        "Premarket freshness audit fixture",
        "Regular-session freshness audit fixture",
        "After-close freshness audit fixture",
    ],
    "Candidate Lifecycle": ["Candidate lifecycle preview fixtures"],
    "Authorization/Recovery": ["Production verifier", "Docker capacity"],
    "Resources": ["Resource capacity df", "Resource capacity inodes", "Resource capacity memory", "Docker capacity"],
    "Clock/Session": ["Clock session", "Scheduler phase fixtures"],
}

def aggregate(names: list[str]) -> str:
    statuses = [row["status"] for row in rows if row["area"] in names]
    if not statuses:
        return "WATCH"
    if "FAIL" in statuses:
        return "FAIL"
    if "WATCH" in statuses:
        return "WATCH"
    return "PASS"

scoreboard = {area: aggregate(names) for area, names in areas.items()}
ready = all(status == "PASS" for status in scoreboard.values())
known_risks = [
    f"{row['area']}: {row['reason']}"
    for row in rows
    if row["status"] != "PASS"
]
payload = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "commit": commit,
    "status": "PASS" if ready else ("FAIL" if any(v == "FAIL" for v in scoreboard.values()) else "WATCH"),
    "scoreboard": scoreboard,
    "ready_for_clean_session": ready,
    "roy_action_required": not ready,
    "known_risks": known_risks,
    "checks": rows,
    "fixture_isolation": str(result_dir),
    "guardrail": (
        "Pre-session acceptance only. Fixed allowlisted commands. No broker/live execution, "
        "no authoritative validation ledger mutation, no arbitrary Docker/Python/journal invocation."
    ),
}
(result_dir / "presession_acceptance.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
lines = [
    "# Pre-Session Acceptance",
    "",
    f"Generated UTC: {payload['generated_at_utc']}",
    f"Commit: {commit}",
    "",
    "## Scoreboard",
    "",
]
for area, status in scoreboard.items():
    lines.append(f"- {area}: {status}")
lines.extend(
    [
        "",
        f"READY FOR CLEAN SESSION: {'YES' if ready else 'NO'}",
        f"ROY ACTION REQUIRED: {'YES' if not ready else 'NO'}",
        "",
        "## Known Risks",
        "",
    ]
)
if known_risks:
    lines.extend(f"- {risk}" for risk in known_risks)
else:
    lines.append("- None")
lines.extend(["", "## Guardrail", "", payload["guardrail"], ""])
(result_dir / "presession_acceptance.md").write_text("\n".join(lines), encoding="utf-8")
print(f"PRE-SESSION ACCEPTANCE: {payload['status']}")
print(f"READY FOR CLEAN SESSION: {'YES' if ready else 'NO'}")
print(f"ROY ACTION REQUIRED: {'YES' if not ready else 'NO'}")
print(f"Saved: {result_dir / 'presession_acceptance.json'}")
PY

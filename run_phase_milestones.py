"""Build the Project Gwala phase and milestone dashboard.

This report turns the current research/paper workflow into a plain-English
roadmap. It does not fetch data, create alerts, import paper trades, place
orders, or connect to broker execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table


PHASE_COLUMNS = [
    "phase_id",
    "phase",
    "status",
    "progress",
    "next_blocker",
    "next_action",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build phase milestone dashboard.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object or return an empty dict."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def percent(current: float, required: float) -> float:
    """Return capped progress percent."""

    if required <= 0:
        return 100.0
    return round(min(max(current / required, 0.0), 1.0) * 100, 1)


def phase_row(
    phase_id: int,
    phase: str,
    status: str,
    current: float,
    required: float,
    next_blocker: str,
    next_action: str,
) -> dict[str, Any]:
    """Return one phase row."""

    return {
        "phase_id": phase_id,
        "phase": phase,
        "status": status,
        "current": current,
        "required": required,
        "percent": percent(current, required),
        "progress": f"{current:g} / {required:g}",
        "next_blocker": next_blocker,
        "next_action": next_action,
    }


def paper_allowed_count(output_dir: Path) -> int:
    """Return allowed completed paper trades."""

    review = read_csv_or_empty(output_dir / "paper_review_clean_trades.csv")
    if review.empty or "signal_status" not in review.columns:
        return 0
    return int((review["signal_status"].astype(str) == "allowed").sum())


def integrity_issue_count(output_dir: Path) -> int:
    """Return count of data-integrity rows requiring attention."""

    integrity = read_csv_or_empty(output_dir / "candle_data_integrity.csv")
    if integrity.empty or "status" not in integrity.columns:
        return 0
    return int((integrity["status"].astype(str) != "ok").sum())


def synced_report_state(output_dir: Path) -> dict[str, Any]:
    """Return whether the core market-readiness reports exist together."""

    required_files = [
        output_dir / "daily_paper_signal_scanner.csv",
        output_dir / "position_sizing.csv",
        output_dir / "market_regime_router.json",
        output_dir / "pre_entry_review.json",
        output_dir / "refresh_status.json",
    ]
    missing = [path.name for path in required_files if not path.exists()]
    modified_times = [path.stat().st_mtime for path in required_files if path.exists()]
    age_spread_seconds = round(max(modified_times) - min(modified_times), 1) if len(modified_times) > 1 else 0.0
    return {
        "status": "pass" if not missing else "missing_inputs",
        "missing_files": missing,
        "age_spread_seconds": age_spread_seconds,
        "report_count": len(required_files) - len(missing),
        "required_report_count": len(required_files),
    }


def market_readiness_summary(
    output_dir: Path,
    refresh: dict[str, Any],
    pre_entry: dict[str, Any],
    router: dict[str, Any],
    allowed_paper: int,
    integrity_issues: int,
    automation_ok: bool,
) -> dict[str, Any]:
    """Summarize the current path from market data to review-first paper candidates."""

    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(output_dir / "position_sizing.csv")
    sync = synced_report_state(output_dir)
    scanner_rows = int(len(scanner))
    sizing_rows = int(len(sizing))
    allowed_scanner_rows = (
        int((scanner["scanner_status"].astype(str) == "allowed").sum())
        if not scanner.empty and "scanner_status" in scanner.columns
        else 0
    )
    current_signal_rows = (
        int((scanner["signal_freshness"].astype(str) == "current_candle").sum())
        if not scanner.empty and "signal_freshness" in scanner.columns
        else 0
    )
    review_first = int(router.get("review_first_count", 0) or 0)
    caution_review = int(router.get("caution_review_count", 0) or 0)
    pre_entry_ready = int(pre_entry.get("ready_for_manual_review", 0) or 0)
    paper_blocked = bool(refresh.get("paper_import_blocked", True))
    refresh_status = str(refresh.get("status", "missing") or "missing")
    data_ready = refresh_status in {"ready", "current_session_data"} and not paper_blocked
    pipes_synced = sync["status"] == "pass" and scanner_rows >= review_first and scanner_rows >= pre_entry_ready

    if not pipes_synced:
        status = "blocked"
        blocker = "Core scanner, sizing, router, pre-entry, or refresh reports are missing."
        action = "Run the local readiness refresh so every report rebuilds from the same inputs."
    elif integrity_issues or not automation_ok:
        status = "blocked"
        blocker = "Data integrity or automation timeline needs attention."
        action = "Fix data integrity or automation warnings before trusting new paper candidates."
    elif not data_ready:
        status = "waiting_for_market_data"
        blocker = refresh.get("reason") or refresh.get("paper_import_reason") or "Current-session data is not paper-import ready."
        action = refresh.get("next_action") or "Refresh market data during the next regular market session."
    elif review_first > 0 and pre_entry_ready > 0:
        status = "review_first_ready"
        blocker = "Manual review is required before any local paper entry."
        action = "Open Pre-Entry Review and manually decide whether to log the paper trade."
    elif review_first > 0:
        status = "router_ready_pre_entry_blocked"
        blocker = pre_entry.get("next_action") or "Router found review-first candidates, but pre-entry review blocked them."
        action = "Open Pre-Entry Review and resolve the listed blockers."
    else:
        status = "scanning"
        blocker = "No review-first current-candle candidate right now."
        action = router.get("next_action") or "Keep market-hours scans running and let the router surface review-first candidates."

    return {
        "status": status,
        "data_status": refresh_status,
        "data_ready_for_paper": data_ready,
        "pipes_synced": pipes_synced,
        "sync": sync,
        "scanner_rows": scanner_rows,
        "allowed_scanner_rows": allowed_scanner_rows,
        "current_signal_rows": current_signal_rows,
        "sizing_rows": sizing_rows,
        "review_first_candidates": review_first,
        "caution_review_candidates": caution_review,
        "pre_entry_ready": pre_entry_ready,
        "official_paper_trades": allowed_paper,
        "official_paper_goal": 30,
        "paper_progress_percent": percent(allowed_paper, 30),
        "next_blocker": str(blocker),
        "next_action": str(action),
    }


def build_milestones(output_dir: Path) -> dict[str, Any]:
    """Build milestone payload from existing workflow reports."""

    automation = read_json_or_empty(output_dir / "daily_automation_timeline.json")
    refresh = read_json_or_empty(output_dir / "refresh_status.json")
    pre_entry = read_json_or_empty(output_dir / "pre_entry_review.json")
    router = read_json_or_empty(output_dir / "market_regime_router.json")
    activation = read_json_or_empty(output_dir / "paper_activation_rules.json")
    vwap_gate = read_json_or_empty(output_dir / "vwap_reclaim_reject_paper_watch_gate.json")
    vault = read_json_or_empty(output_dir / "strategy_vault.json")
    queue = read_csv_or_empty(output_dir / "forward_sample_queue.csv")

    allowed_paper = paper_allowed_count(output_dir)
    integrity_issues = integrity_issue_count(output_dir)
    automation_status = str(automation.get("status", "") or "")
    automation_failures = automation.get("recent_failures", [])
    automation_ok = automation_status in {"pass", "action_needed"} and not automation_failures
    data_ok = integrity_issues == 0 and automation_ok

    scanner_ready = int(pre_entry.get("ready_for_manual_review", 0) or 0)
    queue_almost_ready = int((queue["queue_status"].astype(str) == "almost_ready").sum()) if not queue.empty and "queue_status" in queue.columns else 0
    strategies = vault.get("strategies", []) if isinstance(vault.get("strategies", []), list) else []
    vault_strategy_count = int(len(strategies))
    active_strategy_count = int(vault.get("active_strategy_count", 0) or 0)
    research_priority_count = int(vault.get("research_priority_count", 0) or 0)
    research_only_strategy_count = int(vault.get("selector", {}).get("research_only_strategy_count", 0) or 0)
    eligible_strategies = int(activation.get("eligible_strategy_count", 0) or 0)
    market_readiness = market_readiness_summary(
        output_dir=output_dir,
        refresh=refresh,
        pre_entry=pre_entry,
        router=router,
        allowed_paper=allowed_paper,
        integrity_issues=integrity_issues,
        automation_ok=automation_ok,
    )

    vwap_tightened = int(vwap_gate.get("tightened_pass_rows", 0) or 0)
    vwap_walk_forward = int(vwap_gate.get("walk_forward_holding_rows", 0) or 0)
    vwap_shadow = int(vwap_gate.get("shadow_samples", 0) or 0)
    vwap_matured_shadow = int(vwap_gate.get("matured_shadow_samples", 0) or 0)
    vwap_forward = int(vwap_gate.get("forward_observations", 0) or 0)
    vwap_matured_forward = int(vwap_gate.get("matured_forward_observations", 0) or 0)
    vwap_gate_decision = str(vwap_gate.get("decision", "missing") or "missing")
    vwap_next_blocker = str(vwap_gate.get("next_blocker", "Run VWAP Reclaim/Reject gate.") or "")

    phase4_current = min(vwap_tightened, 1) + min(vwap_walk_forward, 1) + min(vwap_shadow, 10) + min(vwap_matured_shadow, 5) + min(vwap_forward, 10) + min(vwap_matured_forward, 5)
    phase4_required = 32

    phases = [
        phase_row(
            1,
            "Market Readiness Core",
            "complete" if market_readiness["pipes_synced"] and data_ok else "blocked",
            int(market_readiness["pipes_synced"]) + int(data_ok),
            2,
            "None" if market_readiness["pipes_synced"] and data_ok else market_readiness["next_blocker"],
            "Keep data refresh, scanner, sizing, router, and pre-entry review rebuilding together.",
        ),
        phase_row(
            2,
            "Paper Candidate Pipeline",
            "in_progress",
            allowed_paper,
            30,
            "No current-candle paper-ready candidate yet." if scanner_ready == 0 else "Manual paper review needed.",
            "Keep 5-minute scans running; review any current-candle candidate manually.",
        ),
        phase_row(
            3,
            "Strategy Vault Expansion",
            "complete" if vault_strategy_count >= 7 else "in_progress" if vault_strategy_count else "blocked",
            vault_strategy_count,
            7,
            "None" if vault_strategy_count >= 7 else "Add enough distinct strategy families to cover trend, chop, breakout, failure, VWAP control, and gap regimes.",
            "Move completed vault families into evidence gates; do not paper-watch any research strategy until activation rules pass."
            if vault_strategy_count >= 7
            else "Add the missing strategy families to the vault before treating the system as multi-strategy.",
        ),
        phase_row(
            4,
            "Evidence Gates",
            "in_progress" if vwap_gate_decision != "missing" else "blocked",
            phase4_current,
            phase4_required,
            vwap_next_blocker,
            "Collect VWAP Reclaim/Reject shadow and forward samples, then grade matured outcomes after close.",
        ),
        phase_row(
            5,
            "Paper-Watch Promotion",
            "blocked" if eligible_strategies == 0 else "ready_for_review",
            eligible_strategies,
            1,
            "No research strategy is eligible yet." if eligible_strategies == 0 else "Manual promotion review needed.",
            "Do not route any research strategy to paper-watch until activation rules pass.",
        ),
        phase_row(
            6,
            "Paper Trading Validation",
            "future" if eligible_strategies == 0 else "in_progress",
            allowed_paper,
            30,
            "Paper-watch strategy must be promoted before collecting official paper trades.",
            "Collect 30 clean allowed completed paper trades before scaling confidence.",
        ),
        phase_row(
            7,
            "Execution Readiness",
            "future",
            0,
            1,
            "Backtesting, alerts, and paper validation are not complete.",
            "Keep broker execution disabled until paper validation is proven.",
        ),
    ]

    current_phase = next((row for row in phases if row["status"] in {"blocked", "in_progress", "ready_for_review"}), phases[-1])
    overall_percent = round(sum(float(row["percent"]) for row in phases) / len(phases), 1)
    payload = {
        "status": current_phase["status"],
        "current_phase_id": current_phase["phase_id"],
        "current_phase": current_phase["phase"],
        "overall_percent": overall_percent,
        "next_action": current_phase["next_action"],
        "next_blocker": current_phase["next_blocker"],
        "queue_almost_ready": queue_almost_ready,
        "allowed_paper_trades": allowed_paper,
        "eligible_strategy_count": eligible_strategies,
        "market_readiness": market_readiness,
        "strategy_vault": {
            "strategy_count": vault_strategy_count,
            "active_strategy_count": active_strategy_count,
            "research_priority_count": research_priority_count,
            "research_only_strategy_count": research_only_strategy_count,
        },
        "vwap_reclaim_reject": {
            "decision": vwap_gate_decision,
            "next_blocker": vwap_next_blocker,
            "tightened_pass_rows": vwap_tightened,
            "walk_forward_holding_rows": vwap_walk_forward,
            "shadow_samples": vwap_shadow,
            "matured_shadow_samples": vwap_matured_shadow,
            "forward_observations": vwap_forward,
            "matured_forward_observations": vwap_matured_forward,
        },
        "phases": phases,
        "guardrail": "Milestones are status-only. They do not approve trades, place orders, create broker alerts, or enable live execution.",
    }
    return payload


def write_report(path: Path, payload: dict[str, Any]) -> None:
    """Write the readable milestone report."""

    phases = pd.DataFrame(payload["phases"])[PHASE_COLUMNS]
    readiness = payload["market_readiness"]
    vwap = payload["vwap_reclaim_reject"]
    vault = payload["strategy_vault"]
    path.write_text(
        f"""# Project Gwala Phase Milestones

This report shows the project roadmap as operational phases and measurable
milestones.

Important: this is status-only. It does not place orders, create broker alerts,
import paper trades, or enable live trading.

## Current Phase

```text
Phase {payload["current_phase_id"]}: {payload["current_phase"]}
Status: {payload["status"]}
Overall progress: {payload["overall_percent"]}%
Next blocker: {payload["next_blocker"]}
Next action: {payload["next_action"]}
```

## Phase Roadmap

{markdown_table(phases)}

## Market Readiness Control

```text
Status: {readiness["status"]}
Data status: {readiness["data_status"]}
Pipes synced: {readiness["pipes_synced"]}
Scanner rows: {readiness["scanner_rows"]}
Allowed scanner rows: {readiness["allowed_scanner_rows"]}
Current-candle signals: {readiness["current_signal_rows"]}
Review-first candidates: {readiness["review_first_candidates"]}
Pre-entry ready: {readiness["pre_entry_ready"]}
Official paper trades: {readiness["official_paper_trades"]} / {readiness["official_paper_goal"]}
Paper progress: {readiness["paper_progress_percent"]}%
Next blocker: {readiness["next_blocker"]}
Next action: {readiness["next_action"]}
```

## Strategy Vault Coverage

```text
Vault strategy families: {vault["strategy_count"]} / 7
Active paper-watch strategies: {vault["active_strategy_count"]}
Today's research-priority strategies: {vault["research_priority_count"]}
Research-only strategies blocked from paper-watch: {vault["research_only_strategy_count"]}
```

## VWAP Reclaim / Reject Evidence Focus

```text
Gate decision: {vwap["decision"]}
Next blocker: {vwap["next_blocker"]}
Tightened research pass rows: {vwap["tightened_pass_rows"]} / 1
Walk-forward holding rows: {vwap["walk_forward_holding_rows"]} / 1
Shadow samples: {vwap["shadow_samples"]} / 10
Matured shadow outcomes: {vwap["matured_shadow_samples"]} / 5
Forward observations: {vwap["forward_observations"]} / 10
Matured forward outcomes: {vwap["matured_forward_observations"]} / 5
```

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_milestones(args.output_dir)
    json_path = args.output_dir / "phase_milestones.json"
    md_path = args.output_dir / "phase_milestones.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_report(md_path, payload)
    print(f"Phase milestone status: {payload['status']}")
    print(f"Current phase: {payload['current_phase']}")
    print(f"Saved phase milestone report: {md_path}")


if __name__ == "__main__":
    main()

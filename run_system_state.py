"""Write app-ready Project Gwala system state reports.

This command creates structured JSON for a future app/dashboard and a readable
Markdown companion for quick terminal review. It is research/paper workflow
only and does not fetch data, place orders, create alerts, or connect to broker
execution.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from config.runtime_paths import runtime_data_path
from reports.system_state import build_system_state, file_state
from run_playbook import markdown_table


RECOMMENDATION_CHECKLIST = [
    "Refresh Webull market data during the next open market session before acting on scanner rows.",
    "Collect only valid current-candle paper trades until the 30-trade checkpoint.",
    "Review setup health before trusting any approved setup.",
    "Keep AAPL Setup B Short under caution until its math improves.",
    "Preserve app-ready JSON/CSV outputs as the source for any future UI.",
]


def json_safe(value: Any) -> Any:
    """Return a strict-JSON-safe copy of nested report data."""

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build app-ready Project Gwala system state.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--paper-csv", type=Path, default=runtime_data_path("paper_trades.csv"), help="Paper trade log.")
    return parser.parse_args()


def small_table(mapping: dict[str, Any]) -> str:
    """Render a dictionary as a simple Markdown table."""

    rows = []
    for key, value in mapping.items():
        if isinstance(value, (dict, list)):
            display_value = json.dumps(value)
        else:
            display_value = str(value)
        rows.append({"field": key, "value": display_value})
    return markdown_table(pd.DataFrame(rows))


def write_markdown(path: Path, state: dict[str, Any]) -> None:
    """Write a readable Markdown version of the system state."""

    checklist = "\n".join(f"- [ ] {item}" for item in RECOMMENDATION_CHECKLIST)
    attention = pd.DataFrame(state["setup_health"]["attention_setups"])

    path.write_text(
        f"""# Project Gwala System State

This is the app-ready system state snapshot for the research and paper
workflow.

Important: this remains paper/research only. Live trading, broker order
execution, and real-money readiness are disabled.

## Verdict

```text
{state["readiness_verdict"]}
```

## Market

{small_table(state["market"])}

## App Health

{small_table({
    "generated_at_et": state["app_health"]["generated_at_et"],
    "system_state_json": state["app_health"]["source_file_states"]["system_state_json"]["modified_et"],
    "refresh_status_json": state["app_health"]["source_file_states"]["refresh_status_json"]["modified_et"],
    "premarket_verification_json": state["app_health"]["source_file_states"]["premarket_verification_json"]["modified_et"],
    "setup_replay_json": state["app_health"]["source_file_states"]["setup_replay_json"]["modified_et"],
    "dashboard_md": state["app_health"]["source_file_states"]["dashboard_md"]["modified_et"],
    "scanner_csv": state["app_health"]["source_file_states"]["scanner_csv"]["modified_et"],
    "forward_observations_csv": state["app_health"]["source_file_states"]["forward_observations_csv"]["modified_et"],
    "forward_results_csv": state["app_health"]["source_file_states"]["forward_results_csv"]["modified_et"],
    "integrity_csv": state["app_health"]["source_file_states"]["integrity_csv"]["modified_et"],
    "refresh_audit_csv": state["app_health"]["source_file_states"]["refresh_audit_csv"]["modified_et"],
    "setup_health_csv": state["app_health"]["source_file_states"]["setup_health_csv"]["modified_et"],
})}

## Refresh Status

{small_table({
    "status": state.get("refresh_status", {}).get("status", "missing"),
    "next_action": state.get("refresh_status", {}).get("next_action", "Run python run_refresh_status.py."),
    "paper_import_blocked": state.get("refresh_status", {}).get("paper_import_blocked", True),
})}

## Data Flow Sentinel

{small_table({
    "status": state.get("data_flow_sentinel", {}).get("status", "missing"),
    "fail_count": state.get("data_flow_sentinel", {}).get("fail_count", 0),
    "warn_count": state.get("data_flow_sentinel", {}).get("warn_count", 0),
    "next_action": state.get("data_flow_sentinel", {}).get("next_action", "Run python run_data_flow_sentinel.py --output-dir logs."),
})}

## Historical Bucket Sync

{small_table({
    "status": state.get("historical_bucket_sync", {}).get("status", "missing"),
    "target_scanner_session": state.get("historical_bucket_sync", {}).get("target_scanner_session", "unknown"),
    "unified_last_entry": state.get("historical_bucket_sync", {}).get("unified_last_entry", ""),
    "current_buckets": state.get("historical_bucket_sync", {}).get("current_buckets", []),
    "behind_buckets": state.get("historical_bucket_sync", {}).get("behind_buckets", []),
    "missing_buckets": state.get("historical_bucket_sync", {}).get("missing_buckets", []),
    "next_action": state.get("historical_bucket_sync", {}).get("next_action", "Run python run_historical_bucket_sync.py --output-dir logs."),
})}

## Pre-Market Verification

{small_table({
    "status": state.get("premarket_verification", {}).get("status", "not_run"),
    "probe_status": state.get("premarket_verification", {}).get("probe_status", "not_run"),
    "integrity_status": state.get("premarket_verification", {}).get("integrity_status", "not_run"),
    "paper_import_gate_status": state.get("premarket_verification", {}).get("paper_import_gate_status", "not_run"),
    "modified_et": state.get("premarket_verification", {}).get("modified_et", ""),
})}

## Setup Replay

{small_table({
    "count": state.get("setup_replay", {}).get("count", 0),
    "source": "logs/setup_replay.json",
})}

## Strategy Vault

{small_table({
    "market_regime": state.get("strategy_vault", {}).get("regime", {}).get("market_regime", "missing"),
    "volatility_regime": state.get("strategy_vault", {}).get("regime", {}).get("volatility_regime", "missing"),
    "strategy_environment": state.get("strategy_vault", {}).get("regime", {}).get("strategy_environment", "missing"),
    "active_strategy_count": state.get("strategy_vault", {}).get("active_strategy_count", 0),
    "research_priority_count": state.get("strategy_vault", {}).get("research_priority_count", 0),
    "next_action": state.get("strategy_vault", {}).get("next_action", "Run python run_strategy_vault.py."),
    "source": "logs/strategy_vault.json",
})}

## Current-Candle Candidate Panel

{small_table({
    "current_candidate_count": state.get("current_candidates", {}).get("count", 0),
    "ready_for_review_count": state.get("current_candidates", {}).get("ready_for_review_count", 0),
    "source": "logs/daily_paper_signal_scanner.csv + logs/position_sizing.csv",
})}

## Forward Sample Queue

{small_table({
    "verdict": state.get("forward_sample_queue", {}).get("verdict", ""),
    "ready_for_review": state.get("forward_sample_queue", {}).get("summary", {}).get("ready_for_review", 0),
    "blocked_current": state.get("forward_sample_queue", {}).get("summary", {}).get("blocked_current", 0),
    "almost_ready": state.get("forward_sample_queue", {}).get("summary", {}).get("almost_ready", 0),
    "remaining_to_30": state.get("forward_sample_queue", {}).get("summary", {}).get("remaining_to_30", 30),
    "source": "logs/forward_sample_queue.csv",
})}

## Forward Signal Observations

{small_table({
    "observations_logged": state.get("forward_observations", {}).get("rows", 0),
    "allowed_observations": state.get("forward_observations", {}).get("allowed_rows", 0),
    "blocked_watch_only_observations": state.get("forward_observations", {}).get("blocked_rows", 0),
    "latest_observed_at_et": state.get("forward_observations", {}).get("latest_observed_at_et", ""),
    "source": "data/forward_signal_observations.csv",
})}

## Forward Validation Outcomes

{small_table({
    "reviewed_observations": state.get("forward_validation", {}).get("reviewed_observations", 0),
    "matured_outcomes": state.get("forward_validation", {}).get("matured_outcomes", 0),
    "allowed_average_r": state.get("forward_validation", {}).get("allowed_average_r", 0),
    "blocked_average_r": state.get("forward_validation", {}).get("blocked_average_r", 0),
    "reconciliation_status_counts": state.get("forward_validation", {}).get("reconciliation_status_counts", {}),
    "integrity_issue_count": state.get("forward_validation", {}).get("integrity_issue_count", 0),
    "refresh_audit_rows": state.get("forward_validation", {}).get("refresh_audit_rows", 0),
})}

## Paper Progress Visualization

{small_table({
    "completed_trades": state.get("paper_visualization", {}).get("completed_trades", 0),
    "allowed_completed_trades": state.get("paper_visualization", {}).get("allowed_completed_trades", 0),
    "total_r": state.get("paper_visualization", {}).get("total_r", 0),
    "first_gate_percent": state.get("paper_visualization", {}).get("first_gate_percent", 0),
    "strong_gate_percent": state.get("paper_visualization", {}).get("strong_gate_percent", 0),
    "source": "logs/paper_review_clean_trades.csv",
})}

## Risk Guard

{small_table(state.get("risk_guard", {}))}

## Data Freshness

{small_table(state["data_freshness"])}

## Scanner

{small_table(state["scanner"])}

## Position Sizing

{small_table(state["position_sizing"])}

## Paper Progress

{small_table(state["paper_progress"])}

## Setup Health

{small_table({
    "rows": state["setup_health"]["rows"],
    "status_counts": state["setup_health"]["status_counts"],
    "attention_count": state["setup_health"]["attention_count"],
})}

## Setup Health Attention List

{markdown_table(attention)}

## Recommendation Checklist

{checklist}

## App Files

```text
logs/system_state.json
logs/system_state.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    state = build_system_state(output_dir=args.output_dir, paper_csv=args.paper_csv)
    json_path = args.output_dir / "system_state.json"
    md_path = args.output_dir / "system_state.md"

    json_path.write_text(json.dumps(json_safe(state), indent=2, allow_nan=False), encoding="utf-8")
    write_markdown(md_path, state)
    state["app_health"]["source_file_states"]["system_state_json"] = file_state(json_path)
    state["app_health"]["source_file_states"]["system_state_md"] = file_state(md_path)
    json_path.write_text(json.dumps(json_safe(state), indent=2, allow_nan=False), encoding="utf-8")
    write_markdown(md_path, state)

    print(f"Saved system state JSON: {json_path}")
    print(f"Saved system state report: {md_path}")


if __name__ == "__main__":
    main()

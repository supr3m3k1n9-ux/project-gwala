"""Build a fast-to-market manual paper-watch sprint report.

This is the bridge between the strategy vault, activation rules, and the
market-regime router. It highlights the safest current review lane without
loosening scanner rules or counting anything as an official paper trade.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from run_playbook import markdown_table


PRIMARY_STRATEGY_ID = "trend_pullback_continuation"
PAPER_TRADE_GATE = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the market sprint mode report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--paper-csv", type=Path, default=Path("data/paper_trades.csv"), help="Official paper trade log.")
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
    """Read a CSV if it exists."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def activation_by_strategy(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return activation rows keyed by strategy id."""

    rows = payload.get("strategies", [])
    if not isinstance(rows, list):
        return {}
    return {str(row.get("strategy_id", "")): row for row in rows if isinstance(row, dict)}


def strategy_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return strategy-vault rows keyed by strategy id."""

    rows = payload.get("strategies", [])
    if not isinstance(rows, list):
        return {}
    return {str(row.get("strategy_id", "")): row for row in rows if isinstance(row, dict)}


def eligible_for_manual_watch(strategy: dict[str, Any], activation: dict[str, Any]) -> bool:
    """Return whether a strategy is eligible for manual paper-watch review."""

    return (
        str(strategy.get("status", "")) == "active_paper_watch"
        or str(strategy.get("paper_watch_decision", "")) == "paper_watch_eligible"
        or str(activation.get("activation_decision", "")) == "paper_watch_eligible"
    )


def choose_primary_lane(vault: dict[str, Any], activation: dict[str, Any]) -> dict[str, Any]:
    """Choose the sprint's primary review lane."""

    strategies = strategy_by_id(vault)
    activations = activation_by_strategy(activation)
    primary = strategies.get(PRIMARY_STRATEGY_ID, {})
    primary_activation = activations.get(PRIMARY_STRATEGY_ID, {})
    if primary and eligible_for_manual_watch(primary, primary_activation):
        return {
            "strategy_id": PRIMARY_STRATEGY_ID,
            "strategy": primary.get("name", "Trend Pullback Continuation"),
            "lane_status": "primary_paper_watch_lane",
            "reason": "Trend Pullback is paper-watch eligible and should be reviewed first when a fresh current-candle row appears.",
            "paper_watch_decision": primary_activation.get("activation_decision", primary.get("paper_watch_decision", "")),
            "evidence_note": primary.get("evidence_note", ""),
        }

    active_rows = [
        strategy
        for strategy_id, strategy in strategies.items()
        if eligible_for_manual_watch(strategy, activations.get(strategy_id, {}))
    ]
    if active_rows:
        strategy = active_rows[0]
        strategy_id = str(strategy.get("strategy_id", ""))
        strategy_activation = activations.get(strategy_id, {})
        return {
            "strategy_id": strategy_id,
            "strategy": strategy.get("name", strategy_id),
            "lane_status": "fallback_paper_watch_lane",
            "reason": "Primary Trend Pullback is not eligible, so the sprint falls back to the first eligible manual paper-watch lane.",
            "paper_watch_decision": strategy_activation.get("activation_decision", strategy.get("paper_watch_decision", "")),
            "evidence_note": strategy.get("evidence_note", ""),
        }

    return {
        "strategy_id": "",
        "strategy": "No eligible paper-watch lane",
        "lane_status": "blocked",
        "reason": "No strategy has passed the activation gate for manual paper-watch review.",
        "paper_watch_decision": "not_ready",
        "evidence_note": "",
    }


def current_review_rows(router: dict[str, Any], primary_strategy_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return primary and all review-first router candidates."""

    rows = router.get("candidates", [])
    frame = pd.DataFrame(rows if isinstance(rows, list) else [])
    if frame.empty or "candidate_route" not in frame.columns:
        return pd.DataFrame(), pd.DataFrame()
    review = frame[frame["candidate_route"].astype(str) == "review_first"].copy()
    primary = review[review["strategy_id"].astype(str) == primary_strategy_id].copy() if not review.empty else pd.DataFrame()
    return primary, review


def paper_progress(paper_csv: Path) -> dict[str, Any]:
    """Return official paper trade count. Probation rows are intentionally excluded."""

    paper = read_csv_or_empty(paper_csv)
    if "invalid_for_validation" in paper.columns:
        invalid = paper["invalid_for_validation"].astype(str).str.lower().isin(["1", "true", "yes", "y"])
        paper = paper[~invalid].copy()
    count = int(len(paper))
    return {
        "official_paper_trades": count,
        "required_paper_trades": PAPER_TRADE_GATE,
        "remaining_to_first_gate": max(PAPER_TRADE_GATE - count, 0),
        "progress_pct": round(min(count / PAPER_TRADE_GATE, 1.0) * 100, 1),
    }


def build_payload(output_dir: Path, paper_csv: Path = Path("data/paper_trades.csv")) -> dict[str, Any]:
    """Build the sprint payload from existing reports."""

    vault = read_json_or_empty(output_dir / "strategy_vault.json")
    activation = read_json_or_empty(output_dir / "paper_activation_rules.json")
    router = read_json_or_empty(output_dir / "market_regime_router.json")
    refresh = read_json_or_empty(output_dir / "refresh_status.json")
    sentinel = read_json_or_empty(output_dir / "data_flow_sentinel.json")
    accelerated = read_json_or_empty(output_dir / "accelerated_paper_validation.json")

    lane = choose_primary_lane(vault, activation)
    primary_candidates, review_candidates = current_review_rows(router, str(lane.get("strategy_id", "")))
    progress = paper_progress(paper_csv)
    review_first_count = int(len(review_candidates))
    primary_review_count = int(len(primary_candidates))

    if primary_review_count:
        sprint_status = "ready_to_review_primary_lane"
        next_action = "Review the primary Trend Pullback candidate with the manual checklist and paper-entry packet."
    elif review_first_count:
        sprint_status = "review_other_first_rank_candidate"
        next_action = "Review the first-rank router candidate, but keep Trend Pullback as the primary watch lane."
    elif lane.get("lane_status") in {"primary_paper_watch_lane", "fallback_paper_watch_lane"}:
        sprint_status = "eligible_waiting_for_fresh_signal"
        next_action = "Keep five-minute scans running. Do not paper-log until a fresh current-candle router row becomes review_first."
    else:
        sprint_status = "blocked"
        next_action = "Keep research/scanning active; no strategy is eligible for manual paper-watch review yet."

    payload = {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": sprint_status,
        "primary_lane": lane,
        "review_first_count": review_first_count,
        "primary_review_first_count": primary_review_count,
        "paper_progress": progress,
        "accelerated_scan": {
            "ready": int(accelerated.get("ready", 0) or 0),
            "almost_ready": int(accelerated.get("almost_ready", 0) or 0),
            "current_candidates": int(accelerated.get("current_candidates", 0) or 0),
            "scan_symbols": accelerated.get("scan_symbols", []),
        },
        "data_sync": {
            "refresh_status": refresh.get("status", "unknown"),
            "data_flow_sentinel": sentinel.get("status", "unknown"),
        },
        "next_action": next_action,
        "guardrail": (
            "Market sprint mode is manual review guidance only. It never loosens scanner rules, "
            "imports paper trades, counts probation rows, places broker orders, or enables live execution."
        ),
        "primary_candidates": primary_candidates.to_dict("records") if not primary_candidates.empty else [],
        "review_first_candidates": review_candidates.to_dict("records") if not review_candidates.empty else [],
    }
    return payload


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    """Write the sprint report."""

    lane = pd.DataFrame([payload["primary_lane"]])
    progress = pd.DataFrame([payload["paper_progress"]])
    sync = pd.DataFrame([payload["data_sync"]])
    candidates = pd.DataFrame(payload["review_first_candidates"])
    path.write_text(
        f"""# Market Sprint Mode

Generated: {payload["generated_at_et"]}

Status: `{payload["status"]}`

## Primary Review Lane

{markdown_table(lane)}

## Paper Progress

{markdown_table(progress)}

## Data Sync

{markdown_table(sync)}

## Next Action

```text
{payload["next_action"]}
```

## Review-First Candidates

{markdown_table(candidates)}

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
    payload = build_payload(args.output_dir, args.paper_csv)
    (args.output_dir / "market_sprint_mode.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    write_markdown(args.output_dir / "market_sprint_mode.md", payload)
    print(f"Market sprint mode: {payload['status']}")
    print(f"Saved {args.output_dir / 'market_sprint_mode.md'}")


if __name__ == "__main__":
    main()

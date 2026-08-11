"""Route strategies by current market regime.

This is the traffic-cop layer for Project Gwala. It keeps the broad strategy
net intact, but ranks which strategies and current scanner rows deserve manual
paper-watch attention under the current market condition.

It never fetches data, imports paper trades, places broker orders, creates
broker alerts, or enables live execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.strategy_registry import strategy_id_for_scanner
from run_playbook import markdown_table


REGIME_STRATEGY_MAP = {
    "bullish_trend": {
        "preferred_families": {"trend_continuation", "trend_pullback", "breakout"},
        "preferred_directions": {"long"},
        "environment": "trend",
    },
    "bearish_trend": {
        "preferred_families": {"trend_continuation", "trend_pullback", "breakout"},
        "preferred_directions": {"short"},
        "environment": "trend",
    },
    "gap_and_go": {
        "preferred_families": {"trend_continuation", "trend_pullback", "breakout"},
        "preferred_directions": {"long", "short"},
        "environment": "trend",
    },
    "mixed_chop": {
        "preferred_families": {"vwap_control", "mean_reversion", "failed_breakout"},
        "preferred_directions": {"long", "short"},
        "environment": "chop",
    },
    "range_chop": {
        "preferred_families": {"vwap_control", "mean_reversion", "failed_breakout"},
        "preferred_directions": {"long", "short"},
        "environment": "chop",
    },
}
PAPER_VALIDATION_FRESHNESS = {"current_candle", "grace_candle"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build market regime strategy router.")
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
    """Read a CSV if it exists."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def number_value(value: object) -> float:
    """Return a finite float for routing comparisons."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def clean_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return JSON-safe DataFrame records."""

    if frame.empty:
        return []
    records = []
    for item in frame.to_dict("records"):
        clean = {}
        for key, value in item.items():
            if value is None or pd.isna(value):
                clean[key] = ""
            else:
                clean[key] = value
        records.append(clean)
    return records


def latest_signal_bucket(value: object) -> str:
    """Return a broad time bucket for an ET timestamp string."""

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return "unknown"
    hour = int(parsed.hour)
    minute = int(parsed.minute)
    clock_minutes = hour * 60 + minute
    if clock_minutes < 10 * 60 + 30:
        return "opening_hour"
    if clock_minutes < 12 * 60 + 30:
        return "midday"
    if clock_minutes < 14 * 60 + 30:
        return "afternoon"
    return "late_day"


def activation_lookup(output_dir: Path) -> dict[str, dict[str, Any]]:
    """Return activation rows keyed by strategy id."""

    payload = read_json_or_empty(output_dir / "paper_activation_rules.json")
    rows = payload.get("strategies", []) if isinstance(payload.get("strategies", []), list) else []
    return {str(row.get("strategy_id", "")): row for row in rows}


def late_day_status(output_dir: Path) -> dict[str, Any]:
    """Return whether late-day routing should be caution-only."""

    frame = read_csv_or_empty(output_dir / "candidate_aging.csv")
    if frame.empty or "age_bucket" not in frame.columns or "r_result" not in frame.columns:
        return {
            "late_day_mode": "unknown",
            "late_day_average_r": 0.0,
            "late_day_outcomes": 0,
            "reason": "Candidate aging evidence is unavailable.",
        }
    late = frame[(frame["age_bucket"] == "late_day") & frame["r_result"].notna()].copy()
    if late.empty:
        return {
            "late_day_mode": "unknown",
            "late_day_average_r": 0.0,
            "late_day_outcomes": 0,
            "reason": "No matured late-day outcomes yet.",
        }
    avg_r = round(float(pd.to_numeric(late["r_result"], errors="coerce").fillna(0).mean()), 4)
    mode = "caution_only" if avg_r < 0 else "allowed_with_evidence"
    return {
        "late_day_mode": mode,
        "late_day_average_r": avg_r,
        "late_day_outcomes": int(len(late)),
        "reason": (
            f"Late-day evidence is {avg_r:+.2f}R across {len(late)} outcomes; "
            f"{'keep late signals caution-only' if mode == 'caution_only' else 'late signals can be reviewed normally'}."
        ),
    }


def strategy_matches_regime(strategy: dict[str, Any], regime_name: str) -> bool:
    """Return whether one strategy family fits the current regime."""

    family = str(strategy.get("family", ""))
    route = REGIME_STRATEGY_MAP.get(regime_name, {})
    return family in route.get("preferred_families", set())


def strategy_evidence_ready(strategy: dict[str, Any], activation: dict[str, Any] | None) -> bool:
    """Return whether the strategy has enough evidence for manual paper watch."""

    if strategy.get("status") == "active_paper_watch":
        return True
    if str(strategy.get("paper_watch_decision", "")) == "paper_watch_eligible":
        return True
    if activation and str(activation.get("activation_decision", "")) == "paper_watch_eligible":
        return True
    return False


def route_strategy(
    strategy: dict[str, Any],
    activation: dict[str, Any] | None,
    regime_name: str,
) -> dict[str, Any]:
    """Return a routed strategy row."""

    matches = strategy_matches_regime(strategy, regime_name)
    evidence_ready = strategy_evidence_ready(strategy, activation)
    decision = str(strategy.get("decision", ""))
    if matches and evidence_ready:
        route = "active_today"
        action = "Allow manual paper-watch review if a current-candle, size-ok candidate appears."
    elif matches and decision in {"research_priority", "active"}:
        route = "shadow_today"
        action = "Collect shadow/forward evidence; do not count as official paper trades yet."
    elif not matches and evidence_ready:
        route = "blocked_by_regime"
        action = "Keep available, but do not prioritize today because the market regime does not fit."
    else:
        route = "research_only"
        action = "Keep in research; wait for evidence or a better matching regime."

    return {
        "strategy_id": strategy.get("strategy_id", ""),
        "strategy": strategy.get("name", ""),
        "family": strategy.get("family", ""),
        "regime_match": matches,
        "evidence_ready": evidence_ready,
        "vault_decision": strategy.get("decision", ""),
        "activation_decision": (activation or {}).get("activation_decision", strategy.get("paper_watch_decision", "")),
        "route": route,
        "action": action,
        "reason": strategy.get("reason", ""),
    }


def scanner_strategy_id(row: pd.Series) -> str:
    """Map an approved scanner row to the owning strategy family."""

    return strategy_id_for_scanner(str(row.get("setup", "")), str(row.get("variant", "")))


def route_scanner_row(
    row: pd.Series,
    strategy_routes: dict[str, dict[str, Any]],
    regime_name: str,
    late_day: dict[str, Any],
) -> dict[str, Any]:
    """Return a routed scanner candidate row."""

    strategy_id = scanner_strategy_id(row)
    strategy_route = strategy_routes.get(strategy_id, {})
    direction = str(row.get("direction", ""))
    route = REGIME_STRATEGY_MAP.get(regime_name, {})
    direction_match = direction in route.get("preferred_directions", {"long", "short"})
    freshness = str(row.get("signal_freshness", ""))
    validation_lane = str(row.get("validation_lane", ""))
    scanner_status = str(row.get("scanner_status", ""))
    time_bucket = latest_signal_bucket(row.get("candidate_entry_et", row.get("latest_signal_et", "")))
    base_route = str(strategy_route.get("route", "research_only"))

    if scanner_status != "allowed":
        candidate_route = "not_ready"
        action = "Wait; scanner rules are not fully aligned."
    elif freshness not in PAPER_VALIDATION_FRESHNESS:
        candidate_route = "stale_or_earlier_today"
        action = "Do not paper-log; keep as historical/learning context."
    elif not direction_match:
        candidate_route = "blocked_by_regime"
        action = "Do not prioritize because direction conflicts with current regime."
    elif time_bucket == "late_day" and late_day.get("late_day_mode") == "caution_only":
        candidate_route = "caution_review"
        action = "Manual caution review only; late-day evidence is currently weak."
    elif base_route == "active_today":
        candidate_route = "review_first"
        action = (
            "Manual B-tier grace review only; require fresh sizing, Paper Gate, and Options Contract Gate."
            if freshness == "grace_candle"
            else "Review first for manual paper-watch sizing and checklist."
        )
    elif base_route == "shadow_today":
        candidate_route = "shadow_only"
        action = "Track as shadow/forward evidence; do not count as official paper trade."
    else:
        candidate_route = base_route
        action = "Keep out of paper watch for now."

    return {
        "symbol": row.get("symbol", ""),
        "setup": row.get("setup", ""),
        "direction": direction,
        "variant": row.get("variant", ""),
        "exit_profile": row.get("exit_profile", ""),
        "strategy_id": strategy_id,
        "scanner_status": scanner_status,
        "signal_freshness": freshness,
        "validation_lane": validation_lane,
        "candidate_entry_et": row.get("candidate_entry_et", row.get("latest_signal_et", "")),
        "time_bucket": time_bucket,
        "regime_direction_match": direction_match,
        "quality_grade": row.get("quality_grade", ""),
        "quality_score": row.get("quality_score", ""),
        "relative_volume": row.get("relative_volume", ""),
        "room_to_target_r": row.get("room_to_target_r", ""),
        "candidate_route": candidate_route,
        "action": action,
    }


def build_router(output_dir: Path) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Build the market regime router payload and tables."""

    vault = read_json_or_empty(output_dir / "strategy_vault.json")
    regime = vault.get("regime", {}) if isinstance(vault.get("regime", {}), dict) else {}
    regime_name = str(regime.get("market_regime", "unknown"))
    strategies = vault.get("strategies", []) if isinstance(vault.get("strategies", []), list) else []
    activation = activation_lookup(output_dir)
    late_day = late_day_status(output_dir)
    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")

    strategy_rows = [route_strategy(strategy, activation.get(str(strategy.get("strategy_id", ""))), regime_name) for strategy in strategies]
    strategy_frame = pd.DataFrame(strategy_rows)
    strategy_routes = {str(row["strategy_id"]): row for row in strategy_rows}

    if scanner.empty:
        candidate_frame = pd.DataFrame()
    else:
        allowed_or_current = scanner[
            scanner["scanner_status"].isin(["allowed", "not_ready"])
            & scanner["setup"].astype(str).ne("")
        ].copy()
        candidate_frame = pd.DataFrame(
            route_scanner_row(row, strategy_routes, regime_name, late_day) for _, row in allowed_or_current.iterrows()
        )

    route_counts = strategy_frame.groupby("route").size().to_dict() if not strategy_frame.empty else {}
    candidate_counts = candidate_frame.groupby("candidate_route").size().to_dict() if not candidate_frame.empty else {}
    review_first = int(candidate_counts.get("review_first", 0))
    caution = int(candidate_counts.get("caution_review", 0))
    next_action = (
        "Review first-rank current candidates with the manual paper checklist."
        if review_first
        else "No review-first candidate right now. Keep scanning; use shadow/caution rows as learning evidence."
        if caution
        else "Keep scanning. The router is preserving the broad strategy net but no current row is first-rank."
    )
    payload = {
        "regime": regime,
        "late_day": late_day,
        "route_counts": {str(key): int(value) for key, value in route_counts.items()},
        "candidate_route_counts": {str(key): int(value) for key, value in candidate_counts.items()},
        "review_first_count": review_first,
        "caution_review_count": caution,
        "next_action": next_action,
        "guardrail": (
            "Router is manual paper-watch guidance only. It does not fetch data, import trades, "
            "place orders, create broker alerts, or enable live execution."
        ),
        "strategies": strategy_rows,
        "candidates": clean_records(candidate_frame),
    }
    return payload, strategy_frame, candidate_frame


def write_outputs(output_dir: Path, payload: dict[str, Any], strategies: pd.DataFrame, candidates: pd.DataFrame) -> None:
    """Write router JSON/CSV/Markdown outputs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "market_regime_router.json"
    strategy_csv = output_dir / "market_regime_router_strategies.csv"
    candidate_csv = output_dir / "market_regime_router_candidates.csv"
    md_path = output_dir / "market_regime_router.md"
    json_path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    strategies.to_csv(strategy_csv, index=False)
    candidates.to_csv(candidate_csv, index=False)

    regime = payload["regime"]
    late = payload["late_day"]
    md_path.write_text(
        f"""# Market Regime Router

This report keeps the broad strategy net, then routes attention based on the
current market regime.

Important: this is research/paper workflow only. It does not fetch data, place
orders, import paper trades, create broker alerts, or enable live execution.

## Regime

```text
Market regime: {regime.get("market_regime", "unknown")}
Volatility: {regime.get("volatility_regime", "unknown")}
Confidence: {regime.get("confidence", "unknown")}
Reason: {regime.get("reason", "")}
Late-day mode: {late.get("late_day_mode", "unknown")} ({late.get("reason", "")})
```

## Next Action

```text
{payload["next_action"]}
```

## Strategy Routes

{markdown_table(strategies)}

## Candidate Routes

{markdown_table(candidates)}

## Guardrail

```text
{payload["guardrail"]}
```

## Files

```text
logs/market_regime_router.json
logs/market_regime_router_strategies.csv
logs/market_regime_router_candidates.csv
logs/market_regime_router.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload, strategies, candidates = build_router(args.output_dir)
    write_outputs(args.output_dir, payload, strategies, candidates)
    print(f"Market regime router: {payload['regime'].get('market_regime', 'unknown')}")
    print(f"Review-first candidates: {payload['review_first_count']}")
    print(f"Saved market regime router report: {args.output_dir / 'market_regime_router.md'}")


if __name__ == "__main__":
    main()

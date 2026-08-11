"""Tier scanner rows into A/B/C paper-validation lanes.

Paper Gate v2 keeps the old hard safety gates intact, but separates alpha
quality into tiers so the workflow can collect forward evidence faster.

It does not place broker orders, write paper trades, create alerts, or enable
real-money trading.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from config.filter_policy import PAPER_GATE_THRESHOLDS
from config.market_calendar import MARKET_TZ
from reports.refresh_status import market_refresh_state
from run_playbook import markdown_table


FIRST_SAMPLE_GATE = 30
VALIDATION_SAMPLE_CSV = Path("data/paper_validation_samples.csv")
HARD_BLOCKER_TEXT = {
    "market is closed",
    "scanner row is not from today's session",
    "signal is outside current_candle or one-M30 grace_candle",
    "missing entry/stop/target/risk plan",
    "risk per share is not positive",
}
PAPER_VALIDATION_FRESHNESS = {"current_candle", "grace_candle"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Paper Gate v2 tiered validation report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--scanner-csv", type=Path, default=Path("logs/daily_paper_signal_scanner.csv"))
    parser.add_argument("--samples-csv", type=Path, default=VALIDATION_SAMPLE_CSV)
    parser.add_argument("--account-size", type=float, default=10_000.0)
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object or return an empty dict."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def number(value: object, default: float = 0.0) -> float:
    """Return a finite float."""

    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return default
    return float(parsed)


def text(value: object) -> str:
    """Return stable text for maybe-empty values."""

    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def split_conditions(value: object) -> list[str]:
    """Split semicolon-separated scanner condition text."""

    return [item.strip() for item in text(value).split(";") if item.strip()]


def router_lookup(router: dict[str, Any]) -> dict[tuple[str, str, str, str, str], dict[str, Any]]:
    """Return router candidates keyed by scanner row identity."""

    rows = router.get("candidates", [])
    if not isinstance(rows, list):
        return {}
    lookup: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (
            text(row.get("symbol")).upper(),
            text(row.get("setup")),
            text(row.get("direction")),
            text(row.get("variant")),
            text(row.get("exit_profile")),
        )
        lookup[key] = row
    return lookup


def row_key(row: pd.Series) -> tuple[str, str, str, str, str]:
    """Return scanner row key."""

    return (
        text(row.get("symbol")).upper(),
        text(row.get("setup")),
        text(row.get("direction")),
        text(row.get("variant")),
        text(row.get("exit_profile")),
    )


def candidate_entry_time(row: pd.Series | dict[str, Any]) -> str:
    """Return the active review entry timestamp for a scanner/gate row."""

    candidate = text(row.get("candidate_entry_et"))
    return candidate or text(row.get("latest_signal_et"))


def timestamp_value(value: object) -> pd.Timestamp | None:
    """Return a parsed timestamp or None."""

    parsed = pd.to_datetime(text(value), errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed


def candidate_identity(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    """Return a duplicate-detection key for A/B sample windows."""

    return (
        text(row.get("symbol")).upper(),
        text(row.get("setup")),
        text(row.get("direction")),
        text(row.get("variant")),
        text(row.get("exit_profile")),
        candidate_entry_time(row),
    )


def sample_counts(samples: pd.DataFrame) -> dict[str, Any]:
    """Return current official validation sample progress."""

    if samples.empty:
        return {
            "official_validation_samples": 0,
            "a_tier_samples": 0,
            "b_tier_samples": 0,
            "completed_samples": 0,
            "remaining_to_30": FIRST_SAMPLE_GATE,
            "progress_pct": 0.0,
        }
    tier = samples.get("sample_tier", pd.Series(dtype=str)).astype(str).str.upper()
    completed = samples.get("outcome_r", pd.Series(dtype=str)).astype(str).str.strip().ne("")
    official = tier.isin(["A", "B"])
    if "invalid_for_validation" in samples.columns:
        invalid = samples["invalid_for_validation"].astype(str).str.lower().isin(["1", "true", "yes", "y"])
        official = official & ~invalid
    count = int(official.sum())
    return {
        "official_validation_samples": count,
        "a_tier_samples": int(((tier == "A") & official).sum()),
        "b_tier_samples": int(((tier == "B") & official).sum()),
        "completed_samples": int((official & completed).sum()),
        "remaining_to_30": max(FIRST_SAMPLE_GATE - count, 0),
        "progress_pct": round(min(count / FIRST_SAMPLE_GATE, 1.0) * 100, 1),
    }


def sample_keys(samples: pd.DataFrame) -> set[tuple[str, str, str, str, str]]:
    """Return sample keys already imported into the validation ledger."""

    if samples.empty:
        return set()
    required = ["sample_date", "entry_time_et", "symbol", "setup", "direction"]
    if any(column not in samples.columns for column in required):
        return set()
    keys: set[tuple[str, str, str, str, str]] = set()
    for _, row in samples.iterrows():
        keys.add(
            (
                text(row.get("sample_date")),
                text(row.get("entry_time_et")),
                text(row.get("symbol")).upper(),
                text(row.get("setup")).lower(),
                text(row.get("direction")).lower(),
            )
        )
    return keys


def entry_time_hhmm(value: object) -> str:
    """Return HH:MM from an ET timestamp when possible."""

    raw = text(value)
    parsed = pd.to_datetime(raw, errors="coerce")
    if not pd.isna(parsed):
        return parsed.strftime("%H:%M")
    return raw[11:16] if len(raw) >= 16 else raw


def plan_complete(row: pd.Series) -> bool:
    """Return whether the scanner row has enough planned trade details."""

    values = [number(row.get("planned_entry")), number(row.get("planned_stop")), number(row.get("planned_target"))]
    risk = number(row.get("risk_per_share"))
    return all(value > 0 for value in values) and risk > 0


def check_score(row: pd.Series) -> float:
    """Return scanner condition score."""

    passed = number(row.get("passed_condition_count"))
    total = number(row.get("condition_count"))
    if total <= 0:
        return 0.0
    return round(passed / total, 4)


def tier_risk_pct(tier: str) -> float:
    """Return max paper-validation risk for a tier."""

    if tier == "A":
        return float(PAPER_GATE_THRESHOLDS["a_risk_pct"])
    if tier == "B":
        return float(PAPER_GATE_THRESHOLDS["b_risk_pct"])
    return 0.0


def suggested_shares(row: pd.Series, tier: str, account_size: float) -> int:
    """Return conservative shares for the validation sample."""

    risk = number(row.get("risk_per_share"))
    if risk <= 0:
        return 0
    budget = account_size * tier_risk_pct(tier)
    return max(0, math.floor(budget / risk))


def ledger_sample_key(row: pd.Series) -> tuple[str, str, str, str, str]:
    """Return the validation-sample key for a Candidate Ledger row."""

    return (
        text(row.get("trade_date")),
        entry_time_hhmm(row.get("candidate_entry_et")),
        text(row.get("symbol")).upper(),
        text(row.get("setup")).lower(),
        text(row.get("direction")).lower(),
    )


def ledger_row_identity(row: pd.Series) -> tuple[str, str, str, str, str, str]:
    """Return a stable identity for duplicate ledger promotion rows."""

    return (
        text(row.get("trade_date")),
        text(row.get("symbol")).upper(),
        text(row.get("setup")).lower(),
        text(row.get("direction")).lower(),
        text(row.get("candidate_entry_et")),
        text(row.get("paper_gate_tier")).upper(),
    )


def ledger_ready_row(row: pd.Series) -> dict[str, Any]:
    """Convert a preserved Candidate Ledger A/B row into a Paper Gate sample."""

    tier = text(row.get("paper_gate_tier")).upper()
    freshness = text(row.get("freshness_lane"))
    shares = int(number(row.get("size"))) if number(row.get("size")) > 0 else 0
    return {
        "sample_tier": tier,
        "sample_status": "ready_for_validation_sample",
        "counts_toward_30": tier in {"A", "B"},
        "counts_toward_live_readiness": tier == "A",
        "symbol": text(row.get("symbol")).upper(),
        "setup": text(row.get("setup")),
        "direction": text(row.get("direction")),
        "strategy_id": text(row.get("strategy_id")),
        "variant": text(row.get("variant")),
        "exit_profile": text(row.get("exit_profile")),
        "scan_date": text(row.get("trade_date")),
        "latest_candle_et": text(row.get("latest_candle_et")),
        "latest_signal_et": text(row.get("source_signal_et")),
        "source_signal_et": text(row.get("source_signal_et")),
        "candidate_entry_et": text(row.get("candidate_entry_et")),
        "signal_freshness": freshness,
        "validation_lane": tier,
        "manual_review_required": True,
        "fresh_plan_source": "candidate_window_ledger",
        "scanner_status": text(row.get("scanner_status")),
        "router_route": text(row.get("router_status")),
        "quality_grade": text(row.get("quality_grade")),
        "quality_score": number(row.get("quality_score")),
        "relative_volume": round(number(row.get("relative_volume")), 4),
        "room_to_target_r": round(number(row.get("room_to_target_r")), 4),
        "check_score": number(row.get("check_score")),
        "soft_miss_count": 0,
        "missing_conditions": "",
        "planned_entry": number(row.get("entry")),
        "planned_stop": number(row.get("stop")),
        "planned_target": number(row.get("target")),
        "risk_per_share": number(row.get("risk_per_share")),
        "sample_risk_pct": tier_risk_pct(tier),
        "suggested_shares": shares,
        "reason": text(row.get("paper_gate_reason")) or "Preserved A/B Candidate Ledger state.",
        "guardrail_blockers": "",
        "promotion_source": "candidate_window_ledger",
        "ledger_first_seen_at": text(row.get("first_seen_at")),
    }


def ready_samples_from_candidate_ledger(
    ledger: pd.DataFrame,
    *,
    market: dict[str, Any],
    samples: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Return preserved same-session A/B rows that remain eligible for promotion."""

    if ledger.empty:
        return []
    today = text(market.get("today"))
    existing_sample_keys = sample_keys(samples)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for _, row in ledger.iterrows():
        tier = text(row.get("paper_gate_tier")).upper()
        identity = ledger_row_identity(row)
        if identity in seen:
            continue
        if today and text(row.get("trade_date")) != today:
            continue
        if tier not in {"A", "B"}:
            continue
        if text(row.get("paper_gate_status")) != "ready_for_validation_sample":
            continue
        if text(row.get("freshness_lane")) not in PAPER_VALIDATION_FRESHNESS:
            continue
        if ledger_sample_key(row) in existing_sample_keys:
            continue
        seen.add(identity)
        rows.append(ledger_ready_row(row))
    return apply_duplicate_grace_guard(rows)


def classify_row(
    row: pd.Series,
    *,
    market: dict[str, Any],
    router_row: dict[str, Any],
    account_size: float,
) -> dict[str, Any]:
    """Classify one scanner row into A/B/C/blocked."""

    today = str(market.get("today", ""))
    market_open = bool(market.get("market_is_open", False))
    same_session = text(row.get("scan_date")) == today
    freshness = text(row.get("signal_freshness"))
    current_candle = freshness == "current_candle"
    grace_candle = freshness == "grace_candle"
    plan_ok = plan_complete(row)
    score = check_score(row)
    scanner_status = text(row.get("scanner_status"))
    router_route = text(router_row.get("candidate_route")) or "unrouted"
    quality_score = number(row.get("quality_score"))
    rel_volume = number(row.get("relative_volume"))
    room = number(row.get("room_to_target_r"))
    missing = split_conditions(row.get("missing_conditions"))

    hard_blockers: list[str] = []
    if not market_open:
        hard_blockers.append("market is closed")
    if not same_session:
        hard_blockers.append("scanner row is not from today's session")
    if freshness not in PAPER_VALIDATION_FRESHNESS:
        hard_blockers.append("signal is outside current_candle or one-M30 grace_candle")
    if grace_candle:
        source_time = timestamp_value(row.get("source_signal_et", row.get("latest_signal_et")))
        candidate_time = timestamp_value(candidate_entry_time(row))
        if text(row.get("fresh_plan_source")) != "latest_grace_candle":
            hard_blockers.append("B-tier grace missing refreshed current-candle plan")
        if source_time is None or candidate_time is None:
            hard_blockers.append("B-tier grace missing source or candidate timestamp")
        elif candidate_time <= source_time:
            hard_blockers.append("B-tier grace candidate time is not newer than source signal")
        elif candidate_time - source_time > pd.Timedelta(minutes=45):
            hard_blockers.append("B-tier grace is older than one M30 candle")
    if not plan_ok:
        hard_blockers.append("missing entry/stop/target/risk plan")
    if number(row.get("risk_per_share")) <= 0:
        hard_blockers.append("risk per share is not positive")

    soft_misses = len(missing)
    router_supports_a = router_route in {"review_first", "unrouted"}
    router_supports_b = router_route in {"review_first", "caution_review", "unrouted"}

    if hard_blockers:
        tier = "C"
        status = "study_only"
        reason = "Hard safety gate failed: " + "; ".join(hard_blockers)
    elif (
        current_candle
        and scanner_status == "allowed"
        and router_supports_a
        and score >= float(PAPER_GATE_THRESHOLDS["a_min_check_score"])
        and quality_score >= float(PAPER_GATE_THRESHOLDS["a_min_quality_score"])
    ):
        tier = "A"
        status = "ready_for_validation_sample"
        reason = "A-tier: current M30 signal, fresh plan, scanner-allowed, and router-supported."
    elif (
        grace_candle
        and scanner_status == "allowed"
        and router_supports_b
        and score >= float(PAPER_GATE_THRESHOLDS["b_min_check_score"])
        and quality_score >= float(PAPER_GATE_THRESHOLDS["b_min_quality_score"])
        and room > float(PAPER_GATE_THRESHOLDS["b_min_room_to_target_r"])
    ):
        tier = "B"
        status = "ready_for_validation_sample"
        reason = (
            "B-tier grace: source signal was the prior M30 candle, the active row has a fresh plan, "
            "and manual review plus Options Contract Gate are required."
        )
    else:
        tier = "C"
        status = "study_only"
        reason = "C-tier: useful study context, but not clean enough for an official validation sample."

    shares = suggested_shares(row, tier, account_size)
    if status == "ready_for_validation_sample" and shares < 1:
        tier = "C"
        status = "study_only"
        reason = "Risk is too wide for even reduced paper-validation sizing."

    return {
        "sample_tier": tier,
        "sample_status": status,
        "counts_toward_30": tier in {"A", "B"} and status == "ready_for_validation_sample",
        "counts_toward_live_readiness": tier == "A" and status == "ready_for_validation_sample",
        "symbol": text(row.get("symbol")).upper(),
        "setup": text(row.get("setup")),
        "direction": text(row.get("direction")),
        "strategy_id": text(row.get("strategy_id")),
        "variant": text(row.get("variant")),
        "exit_profile": text(row.get("exit_profile")),
        "scan_date": text(row.get("scan_date")),
        "latest_candle_et": text(row.get("latest_candle_et")),
        "latest_signal_et": text(row.get("latest_signal_et")),
        "source_signal_et": text(row.get("source_signal_et", row.get("latest_signal_et"))),
        "candidate_entry_et": candidate_entry_time(row),
        "signal_freshness": freshness,
        "validation_lane": tier if tier in {"A", "B"} else text(row.get("validation_lane")) or "study",
        "manual_review_required": tier in {"A", "B"} and status == "ready_for_validation_sample",
        "fresh_plan_source": text(row.get("fresh_plan_source")),
        "scanner_status": scanner_status,
        "router_route": router_route,
        "quality_grade": text(row.get("quality_grade")),
        "quality_score": quality_score,
        "relative_volume": round(rel_volume, 4),
        "room_to_target_r": round(room, 4),
        "check_score": score,
        "soft_miss_count": soft_misses,
        "missing_conditions": "; ".join(missing),
        "planned_entry": number(row.get("planned_entry")),
        "planned_stop": number(row.get("planned_stop")),
        "planned_target": number(row.get("planned_target")),
        "risk_per_share": number(row.get("risk_per_share")),
        "sample_risk_pct": tier_risk_pct(tier),
        "suggested_shares": shares,
        "reason": reason,
        "guardrail_blockers": "; ".join(hard_blockers),
    }


def apply_duplicate_grace_guard(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Downgrade B rows that duplicate an already-ready A window."""

    a_windows = {
        candidate_identity(row)
        for row in rows
        if row.get("sample_tier") == "A" and row.get("sample_status") == "ready_for_validation_sample"
    }
    guarded: list[dict[str, Any]] = []
    for row in rows:
        if (
            row.get("sample_tier") == "B"
            and row.get("sample_status") == "ready_for_validation_sample"
            and candidate_identity(row) in a_windows
        ):
            downgraded = row.copy()
            downgraded["sample_tier"] = "C"
            downgraded["validation_lane"] = "study"
            downgraded["sample_status"] = "study_only"
            downgraded["counts_toward_30"] = False
            downgraded["counts_toward_live_readiness"] = False
            downgraded["sample_risk_pct"] = 0.0
            downgraded["suggested_shares"] = 0
            downgraded["manual_review_required"] = False
            downgraded["reason"] = "C-tier: B grace row duplicates an already-ready A-tier current window."
            guarded.append(downgraded)
        else:
            guarded.append(row)
    return guarded


def build_payload(
    output_dir: Path = Path("logs"),
    scanner_csv: Path = Path("logs/daily_paper_signal_scanner.csv"),
    samples_csv: Path = VALIDATION_SAMPLE_CSV,
    account_size: float = 10_000.0,
    promotion_source: str = "scanner",
    candidate_ledger_csv: Path = Path("data/candidate_window_ledger.csv"),
) -> dict[str, Any]:
    """Build the Paper Gate v2 payload."""

    scanner = read_csv_or_empty(scanner_csv)
    ledger = read_csv_or_empty(candidate_ledger_csv)
    router = read_json_or_empty(output_dir / "market_regime_router.json")
    samples = read_csv_or_empty(samples_csv)
    market = market_refresh_state()
    routes = router_lookup(router)

    source_used = "scanner_snapshot"
    if promotion_source == "candidate_ledger":
        rows = ready_samples_from_candidate_ledger(ledger, market=market, samples=samples)
        source_used = "candidate_window_ledger" if rows else "scanner_snapshot"
    else:
        rows: list[dict[str, Any]] = []
    if source_used == "scanner_snapshot":
        if scanner.empty:
            rows = []
        else:
            latest_date = ""
            if "scan_date" in scanner.columns and not scanner["scan_date"].dropna().empty:
                latest_date = sorted(str(value) for value in scanner["scan_date"].dropna().unique())[-1]
            latest = scanner[scanner["scan_date"].astype(str) == latest_date].copy() if latest_date else scanner.copy()
            latest = latest.sort_values(["scanner_status", "quality_score"], ascending=[True, False])
            rows = [
                classify_row(row, market=market, router_row=routes.get(row_key(row), {}), account_size=account_size)
                for _, row in latest.iterrows()
            ]
            rows = apply_duplicate_grace_guard(rows)

    frame = pd.DataFrame(rows)
    ready = frame[frame["sample_status"].eq("ready_for_validation_sample")] if not frame.empty else pd.DataFrame()
    tier_counts = frame.groupby("sample_tier").size().to_dict() if not frame.empty else {}
    status_counts = frame.groupby("sample_status").size().to_dict() if not frame.empty else {}
    progress = sample_counts(samples)
    payload = {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": "ready" if not ready.empty else "waiting",
        "sample_gate": progress,
        "ready_sample_count": int(len(ready)),
        "a_tier_ready": int((ready["sample_tier"] == "A").sum()) if not ready.empty else 0,
        "b_tier_ready": int((ready["sample_tier"] == "B").sum()) if not ready.empty else 0,
        "tier_counts": {str(key): int(value) for key, value in tier_counts.items()},
        "status_counts": {str(key): int(value) for key, value in status_counts.items()},
        "thresholds": PAPER_GATE_THRESHOLDS,
        "promotion_source": source_used,
        "rows": rows,
        "ready_samples": ready.to_dict("records") if not ready.empty else [],
        "next_action": (
            "Manually review ready A/B samples. Use A for live-readiness proof; use B as reduced-risk forward evidence."
            if not ready.empty
            else "No A/B validation sample is ready right now. Keep scanning; do not loosen hard safety gates."
        ),
        "guardrail": (
            "Paper Gate v2 can classify A/B/C validation samples, but it never places orders, "
            "never enables live trading, and never lets stale/no-plan rows count toward the 30."
        ),
    }
    return payload


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write Paper Gate v2 JSON, CSV, and Markdown."""

    output_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(payload["rows"])
    ready = pd.DataFrame(payload["ready_samples"])
    (output_dir / "paper_gate_v2.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    frame.to_csv(output_dir / "paper_gate_v2.csv", index=False)

    summary = pd.DataFrame(
        [
            {"field": "status", "value": payload["status"]},
            {"field": "ready_sample_count", "value": payload["ready_sample_count"]},
            {"field": "a_tier_ready", "value": payload["a_tier_ready"]},
            {"field": "b_tier_ready", "value": payload["b_tier_ready"]},
            {"field": "official_validation_samples", "value": payload["sample_gate"]["official_validation_samples"]},
            {"field": "remaining_to_30", "value": payload["sample_gate"]["remaining_to_30"]},
        ]
    )
    thresholds = pd.DataFrame([{"threshold": key, "value": value} for key, value in payload["thresholds"].items()])
    (output_dir / "paper_gate_v2.md").write_text(
        f"""# Paper Gate v2

Generated: {payload["generated_at_et"]}

This report separates hard safety gates from soft alpha-quality filters.

## Summary

{markdown_table(summary)}

## Configurable Thresholds

{markdown_table(thresholds)}

## Ready A/B Samples

{markdown_table(ready)}

## All Tiers

{markdown_table(frame)}

## Next Action

```text
{payload["next_action"]}
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
    payload = build_payload(args.output_dir, args.scanner_csv, args.samples_csv, args.account_size)
    write_outputs(args.output_dir, payload)
    print(f"Paper Gate v2: {payload['status']}")
    print(f"Ready A/B samples: {payload['ready_sample_count']}")
    print(f"Saved {args.output_dir / 'paper_gate_v2.md'}")


if __name__ == "__main__":
    main()

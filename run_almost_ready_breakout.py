"""Explain almost-ready scanner rows.

This read-only report joins the forward sample queue with near-miss, shadow,
and setup-health evidence. It recommends what to study next without changing
scanner eligibility or creating paper trades.
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


GENERIC_BLOCKERS = {
    "market is not open",
    "not a current-candle signal",
    "scanner status is not_ready",
    "Scanner did not mark this setup as allowed.",
}


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if it exists."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def number(value: Any, default: float = 0.0) -> float:
    """Convert a value to float safely."""

    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return default
    return float(parsed)


def split_list(value: Any) -> list[str]:
    """Split semicolon blocker/missing-condition text."""

    if value is None or pd.isna(value):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def core_blockers(value: Any) -> list[str]:
    """Return blockers that are actual strategy conditions."""

    return [item for item in split_list(value) if item not in GENERIC_BLOCKERS]


def setup_health_lookup(setup_health: pd.DataFrame, symbol: str, setup: str) -> dict[str, Any]:
    """Return setup-health details for a symbol/setup."""

    if setup_health.empty or not {"symbol", "setup"}.issubset(setup_health.columns):
        return {"status": "unknown", "expectancy_r": 0.0, "trades": 0}
    matches = setup_health[
        (setup_health["symbol"].astype(str).str.upper() == symbol.upper())
        & (setup_health["setup"].astype(str) == setup)
    ]
    if matches.empty:
        return {"status": "unknown", "expectancy_r": 0.0, "trades": 0}
    row = matches.iloc[0]
    return {
        "status": str(row.get("health_status", "unknown")),
        "expectancy_r": round(number(row.get("expectancy_r")), 4),
        "trades": int(number(row.get("trades"), 0)),
    }


def shadow_lookup(shadow: pd.DataFrame, symbol: str, setup: str) -> dict[str, Any]:
    """Return shadow-outcome evidence for a symbol/setup."""

    if shadow.empty or not {"symbol", "setup", "hypothetical_r"}.issubset(shadow.columns):
        return {"samples": 0, "average_r": 0.0}
    matches = shadow[
        (shadow["symbol"].astype(str).str.upper() == symbol.upper())
        & (shadow["setup"].astype(str) == setup)
        & (shadow.get("evaluation_status", "matured").astype(str) == "matured")
    ].copy()
    if matches.empty:
        return {"samples": 0, "average_r": 0.0}
    matches["hypothetical_r"] = pd.to_numeric(matches["hypothetical_r"], errors="coerce")
    matches = matches.dropna(subset=["hypothetical_r"])
    return {
        "samples": int(len(matches)),
        "average_r": round(float(matches["hypothetical_r"].mean()), 4) if not matches.empty else 0.0,
    }


def blocker_history(near_misses: pd.DataFrame, symbol: str, setup: str, direction: str) -> dict[str, Any]:
    """Summarize historical near-miss blockers for this row."""

    if near_misses.empty or "missing_condition" not in near_misses.columns:
        return {"rows": 0, "top_blockers": ""}
    matches = near_misses[
        (near_misses["symbol"].astype(str).str.upper() == symbol.upper())
        & (near_misses["setup"].astype(str) == setup)
        & (near_misses["direction"].astype(str) == direction)
    ]
    if matches.empty:
        return {"rows": 0, "top_blockers": ""}
    counts = matches.groupby("missing_condition").size().sort_values(ascending=False).head(3)
    top = ", ".join(f"{condition} ({count})" for condition, count in counts.items())
    return {"rows": int(len(matches)), "top_blockers": top}


def action_for_row(
    row: pd.Series,
    blockers: list[str],
    health: dict[str, Any],
    shadow: dict[str, Any],
) -> tuple[str, str]:
    """Return a conservative action label and plain-English reason."""

    check_score = number(row.get("check_score"))
    quality_score = number(row.get("quality_score"))
    room = number(row.get("room_to_target_r"))
    rel_vol = number(row.get("relative_volume"))

    if health["status"] == "caution":
        return "keep_strict", "Setup-health is caution, so this should not be loosened."
    if len(blockers) >= 3:
        return "keep_strict", "Too many actual strategy blockers are missing."
    if shadow["samples"] >= 2 and shadow["average_r"] > 0.25 and check_score >= 0.75:
        return "soften_for_shadow_only", "Shadow evidence is positive, so collect more shadow samples before paper."
    if check_score >= 0.85 and quality_score >= 7 and rel_vol >= 0.8 and room >= 0.25:
        return "paper_watch_if_next_scan_confirms", "Very close row; next fresh current-candle confirmation can be watched closely."
    if check_score >= 0.70:
        return "collect_more_evidence", "Close enough to track, but evidence is not strong enough to loosen."
    return "ignore_noise", "Not close enough to deserve extra attention yet."


def build_rows(output_dir: Path) -> list[dict[str, Any]]:
    """Build breakout rows from current saved evidence."""

    queue = read_csv_or_empty(output_dir / "forward_sample_queue.csv")
    near_misses = read_csv_or_empty(Path("data/near_miss_observations.csv"))
    shadow = read_csv_or_empty(output_dir / "shadow_sample_outcomes.csv")
    setup_health = read_csv_or_empty(output_dir / "setup_health.csv")
    if queue.empty:
        return []

    almost = queue[queue["queue_status"].astype(str) == "almost_ready"].copy()
    rows: list[dict[str, Any]] = []
    for _, row in almost.iterrows():
        symbol = str(row.get("symbol", "")).upper()
        setup = str(row.get("setup", ""))
        direction = str(row.get("direction", ""))
        blockers = core_blockers(row.get("blockers", ""))
        health = setup_health_lookup(setup_health, symbol, setup)
        shadow_evidence = shadow_lookup(shadow, symbol, setup)
        history = blocker_history(near_misses, symbol, setup, direction)
        action, reason = action_for_row(row, blockers, health, shadow_evidence)
        rows.append(
            {
                "action": action,
                "symbol": symbol,
                "setup": setup,
                "direction": direction,
                "check_score_pct": round(number(row.get("check_score")) * 100, 1),
                "quality": f"{row.get('quality_grade', '')} {number(row.get('quality_score')):.0f}".strip(),
                "relative_volume": round(number(row.get("relative_volume")), 4),
                "room_to_target_r": round(number(row.get("room_to_target_r")), 4),
                "core_blockers": "; ".join(blockers) if blockers else "generic timing/freshness only",
                "near_miss_rows": history["rows"],
                "top_historical_blockers": history["top_blockers"],
                "shadow_samples": shadow_evidence["samples"],
                "shadow_average_r": shadow_evidence["average_r"],
                "setup_health": health["status"],
                "setup_expectancy_r": health["expectancy_r"],
                "setup_trades": health["trades"],
                "reason": reason,
            }
        )

    order = {
        "paper_watch_if_next_scan_confirms": 1,
        "soften_for_shadow_only": 2,
        "collect_more_evidence": 3,
        "keep_strict": 4,
        "ignore_noise": 5,
    }
    return sorted(rows, key=lambda item: (order.get(item["action"], 99), -float(item["check_score_pct"])))


def build_payload(output_dir: Path) -> dict[str, Any]:
    """Build JSON-safe breakout payload."""

    rows = build_rows(output_dir)
    counts = pd.Series([row["action"] for row in rows]).value_counts().to_dict() if rows else {}
    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": "watch" if rows else "empty",
        "summary": {str(key): int(value) for key, value in counts.items()},
        "rows": rows,
        "guardrail": "Almost-ready breakout is read-only. It never changes scanner eligibility or imports paper trades.",
    }


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    """Write the breakout report."""

    summary = pd.DataFrame([payload["summary"]]) if payload["summary"] else pd.DataFrame()
    rows = pd.DataFrame(payload["rows"])
    path.write_text(
        f"""# Almost-Ready Breakout

Generated: {payload["generated_at_et"]}

This report explains why near-ready rows did not qualify and whether the
blockers deserve strict enforcement, shadow-only testing, or closer next-scan
watching.

## Action Summary

{markdown_table(summary)}

## Breakout Rows

{markdown_table(rows)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the almost-ready breakout report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload(args.output_dir)
    (args.output_dir / "almost_ready_breakout.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_markdown(args.output_dir / "almost_ready_breakout.md", payload)
    print(f"Almost-ready rows reviewed: {len(payload['rows'])}")
    print(f"Saved {args.output_dir / 'almost_ready_breakout.md'}")


if __name__ == "__main__":
    main()

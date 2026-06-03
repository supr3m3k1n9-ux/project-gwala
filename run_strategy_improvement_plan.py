"""Build a research-only strategy improvement plan.

This report turns the current evidence into a short action list for improving
the VWAP + EMA paper workflow. It does not fetch data, place orders, or change
strategy rules automatically.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV when it exists."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object when it exists."""

    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def number(value: Any, default: float = 0.0) -> float:
    """Convert app/report values into normal floats."""

    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return default
    return float(parsed)


def setup_health_summary(setup_health: pd.DataFrame) -> dict[str, Any]:
    """Summarize setup-health evidence for the plan."""

    if setup_health.empty:
        return {"rows": 0, "watch_more": 0, "caution": 0, "best": ""}

    watch_more = int((setup_health.get("health_status", "") == "watch_more").sum())
    caution = int((setup_health.get("health_status", "") == "caution").sum())
    scored = setup_health.copy()
    scored["expectancy_r"] = pd.to_numeric(scored.get("expectancy_r", 0), errors="coerce").fillna(0.0)
    scored["trades"] = pd.to_numeric(scored.get("trades", 0), errors="coerce").fillna(0).astype(int)
    best = scored.sort_values(["expectancy_r", "trades"], ascending=[False, False]).head(1)
    best_label = ""
    if not best.empty:
        row = best.iloc[0]
        best_label = (
            f"{row.get('symbol', '')} {row.get('setup', '')} "
            f"({int(row.get('trades', 0))} trades, {number(row.get('expectancy_r')):+.2f}R)"
        )
    return {"rows": int(len(setup_health)), "watch_more": watch_more, "caution": caution, "best": best_label}


def late_day_summary(candidate_aging: pd.DataFrame) -> dict[str, Any]:
    """Summarize late-day candidate evidence."""

    if candidate_aging.empty or "age_bucket" not in candidate_aging.columns:
        return {"outcomes": 0, "average_r": 0.0, "status": "not_enough_data"}

    late = candidate_aging[candidate_aging["age_bucket"] == "late_day"].copy()
    result_column = "r_result" if "r_result" in late.columns else "outcome_r" if "outcome_r" in late.columns else ""
    if not result_column:
        return {"outcomes": 0, "average_r": 0.0, "status": "not_enough_data"}

    late[result_column] = pd.to_numeric(late[result_column], errors="coerce")
    outcomes = late.dropna(subset=[result_column])
    average = round(float(outcomes[result_column].mean()), 4) if not outcomes.empty else 0.0
    if len(outcomes) >= 5 and average < 0:
        status = "caution_active"
    elif len(outcomes) >= 5:
        status = "watch_active"
    else:
        status = "collect_more"
    return {"outcomes": int(len(outcomes)), "average_r": average, "status": status}


def promoted_summary(promotion_review: pd.DataFrame) -> dict[str, Any]:
    """Summarize promoted historical candidates."""

    if promotion_review.empty or "promotion_decision" not in promotion_review.columns:
        return {"promoted": 0, "best": ""}

    promoted = promotion_review[promotion_review["promotion_decision"].astype(str) == "paper_watch_candidate"].copy()
    if promoted.empty:
        return {"promoted": 0, "best": ""}

    promoted["expectancy_r"] = pd.to_numeric(promoted.get("expectancy_r", 0), errors="coerce").fillna(0.0)
    promoted["trades"] = pd.to_numeric(promoted.get("trades", 0), errors="coerce").fillna(0).astype(int)
    row = promoted.sort_values(["expectancy_r", "trades"], ascending=[False, False]).iloc[0]
    best = (
        f"{row.get('symbol', '')} {row.get('setup', '')} / {row.get('candidate', '')} "
        f"({int(row.get('trades', 0))} trades, {number(row.get('expectancy_r')):+.2f}R)"
    )
    return {"promoted": int(len(promoted)), "best": best}


def evidence_rows(output_dir: Path) -> list[dict[str, Any]]:
    """Create the seven improvement-plan rows."""

    setup_health = read_csv_or_empty(output_dir / "setup_health.csv")
    promotion_review = read_csv_or_empty(output_dir / "promotion_review.csv")
    candidate_aging = read_csv_or_empty(output_dir / "candidate_aging.csv")
    exit_optimizer = read_csv_or_empty(output_dir / "exit_optimizer_results.csv")
    regime_review = read_csv_or_empty(output_dir / "regime_review.csv")
    near_miss_observations = read_csv_or_empty(Path("data/near_miss_observations.csv"))
    forward_evidence = read_json_or_empty(output_dir / "system_state.json").get("forward_evidence_bridge", {})

    health = setup_health_summary(setup_health)
    late_day = late_day_summary(candidate_aging)
    promoted = promoted_summary(promotion_review)
    official_paper = int(forward_evidence.get("official_paper_trades", 0) or 0)
    shadow_average = number(forward_evidence.get("shadow_average_r", 0))
    forward_average = number(forward_evidence.get("allowed_observation_average_r", 0))

    return [
        {
            "upgrade": "Prioritize high-evidence setups",
            "status": "active",
            "evidence": f"{promoted['promoted']} promoted rows. Best: {promoted['best'] or 'none yet'}.",
            "next_action": "Paper-review promoted setups first, but keep risk capped until the 30-trade gate is reached.",
        },
        {
            "upgrade": "Time-of-day caution",
            "status": late_day["status"],
            "evidence": f"{late_day['outcomes']} late-day outcomes, average {late_day['average_r']:+.2f}R.",
            "next_action": "Treat late-day signals as caution-only while late-day evidence stays negative.",
        },
        {
            "upgrade": "Entry quality scoring",
            "status": "active",
            "evidence": f"{health['rows']} setup-health rows. Watch-more: {health['watch_more']}. Caution: {health['caution']}. Best: {health['best'] or 'none yet'}.",
            "next_action": "Prefer A-grade setups with room, relative volume, and positive setup-health evidence.",
        },
        {
            "upgrade": "Exit refinement",
            "status": "research_ready" if not exit_optimizer.empty else "needs_run",
            "evidence": f"{len(exit_optimizer)} exit optimizer rows available.",
            "next_action": "Use optimizer results for research comparison only; do not change live/paper exit rules without forward samples.",
        },
        {
            "upgrade": "Near-miss learning",
            "status": "active" if not near_miss_observations.empty else "needs_run",
            "evidence": f"{len(near_miss_observations)} near-miss observations available.",
            "next_action": "Review near-misses weekly to see which blocked conditions are filtering good trades versus noise.",
        },
        {
            "upgrade": "Regime filters",
            "status": "research_ready" if not regime_review.empty else "needs_run",
            "evidence": f"{len(regime_review)} regime review rows available.",
            "next_action": "Use regime data as a warning label until it has enough samples to become a hard filter.",
        },
        {
            "upgrade": "Risk caps until proof",
            "status": "active",
            "evidence": f"{official_paper} official paper trades. Forward avg {forward_average:+.2f}R. Shadow avg {shadow_average:+.2f}R.",
            "next_action": "Keep conservative paper risk until 30 allowed completed paper trades prove the workflow.",
        },
    ]


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    """Write the human-readable plan."""

    lines = [
        "# Strategy Improvement Plan",
        "",
        f"Generated: {payload['generated_at_et']}",
        "",
        "Research-only plan for tightening the VWAP + EMA strategy without adding live execution.",
        "",
        "| Upgrade | Status | Evidence | Next action |",
        "|---|---:|---|---|",
    ]
    for row in payload["upgrades"]:
        lines.append(
            "| {upgrade} | {status} | {evidence} | {next_action} |".format(
                upgrade=str(row["upgrade"]).replace("|", "/"),
                status=str(row["status"]).replace("|", "/"),
                evidence=str(row["evidence"]).replace("|", "/"),
                next_action=str(row["next_action"]).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Guardrail",
            "",
            "These upgrades guide manual paper review and research reports only. They do not place broker orders.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the research-only strategy improvement plan.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "safety": "research_and_paper_validation_only",
        "upgrades": evidence_rows(args.output_dir),
    }
    (args.output_dir / "strategy_improvement_plan.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    write_markdown(args.output_dir / "strategy_improvement_plan.md", payload)
    print("Wrote logs/strategy_improvement_plan.md")


if __name__ == "__main__":
    main()

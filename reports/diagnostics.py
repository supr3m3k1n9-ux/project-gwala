"""Signal diagnostics for strategy research.

Diagnostics answer a simple question: where are candles getting filtered out?
That makes strategy improvement more evidence-based and less like guessing.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


DIAGNOSTIC_COLUMNS = [
    "regular_session",
    "entry_window",
    "bullish_regime",
    "bullish_ema_stack",
    "buyers_control_vwap",
    "htf_bullish_bias",
    "above_opening_range",
    "pullback_to_value",
    "bullish_reclaim",
    "long_signal",
    "strong_relative_volume",
    "clean_bull_trend",
    "trend_day_regime",
    "has_room_to_target",
    "elite_filter_pass",
    "elite_long_signal",
    "quality_entry_signal",
]


def summarize_signal_diagnostics(candles: pd.DataFrame) -> pd.DataFrame:
    """Count how often important setup conditions are true."""

    total_candles = len(candles)
    rows = []

    for column in DIAGNOSTIC_COLUMNS:
        if column not in candles.columns:
            continue

        passed = int(candles[column].fillna(False).astype(bool).sum())
        pass_rate = round(passed / total_candles, 4) if total_candles else 0.0
        rows.append(
            {
                "condition": column,
                "passed": passed,
                "total_candles": total_candles,
                "pass_rate": pass_rate,
            }
        )

    if "quality_score" in candles.columns:
        for score, group in candles.groupby("quality_score"):
            rows.append(
                {
                    "condition": f"quality_score_{int(score)}",
                    "passed": len(group),
                    "total_candles": total_candles,
                    "pass_rate": round(len(group) / total_candles, 4) if total_candles else 0.0,
                }
            )

    return pd.DataFrame(rows)


def write_diagnostics_report(diagnostics: pd.DataFrame, path: Path, title: str) -> None:
    """Write a compact Markdown diagnostics report."""

    path.parent.mkdir(parents=True, exist_ok=True)

    if diagnostics.empty:
        table = "No diagnostics were available."
    else:
        columns = list(diagnostics.columns)
        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        for _, row in diagnostics.iterrows():
            lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
        table = "\n".join(lines)

    path.write_text(
        f"""# {title}

This report shows how many candles passed each major setup condition.
Use it to see which filters are blocking trades.

{table}
""",
        encoding="utf-8",
    )

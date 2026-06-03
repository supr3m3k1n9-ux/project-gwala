"""Build a loud-but-safe paper candidate alert report.

This is research and paper-validation only. It flags eligible local paper
review rows from existing scanner and sizing outputs. It does not place orders,
create broker alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from reports.refresh_status import market_refresh_state
from run_dashboard import read_csv_or_empty
from run_playbook import markdown_table


ALERT_COLUMNS = [
    "alert_status",
    "symbol",
    "setup",
    "direction",
    "signal_time_et",
    "entry",
    "stop",
    "target",
    "shares",
    "estimated_risk_dollars",
    "scanner_status",
    "signal_freshness",
    "sizing_status",
    "next_action",
    "blockers",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Project Gwala paper candidate alerts.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where alert reports are saved.")
    return parser.parse_args()


def matching_size(row: pd.Series, sizing: pd.DataFrame) -> pd.Series:
    """Return the matching sizing row for a scanner row."""

    if sizing.empty:
        return pd.Series(dtype=object)
    matches = sizing[
        (sizing["symbol"] == row.get("symbol"))
        & (sizing["setup"] == row.get("setup"))
        & (sizing["direction"] == row.get("direction"))
    ]
    return matches.iloc[0] if not matches.empty else pd.Series(dtype=object)


def build_alert_rows(scanner: pd.DataFrame, sizing: pd.DataFrame, market: dict[str, object]) -> pd.DataFrame:
    """Build alert rows from current scanner and sizing outputs."""

    if scanner.empty:
        return pd.DataFrame(columns=ALERT_COLUMNS)

    candidates = scanner[
        scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
        & (scanner["signal_freshness"] == "current_candle")
    ].copy()
    if candidates.empty:
        return pd.DataFrame(columns=ALERT_COLUMNS)

    rows = []
    for _, row in candidates.iterrows():
        size = matching_size(row, sizing)
        blockers = []
        market_open = bool(market.get("market_is_open", False))
        same_session = str(row.get("scan_date", "")) == str(market.get("today", ""))
        scanner_allowed = row.get("scanner_status") == "allowed"
        sizing_ok = size.get("sizing_status", "") == "size_ok"

        if not market_open:
            blockers.append("market is not open")
        if not same_session:
            blockers.append("scanner row is not from today's open session")
        if not scanner_allowed:
            blockers.append("scanner status is not allowed")
        if not sizing_ok:
            blockers.append(str(size.get("sizing_reason", "position sizing is not size_ok")))

        ready = not blockers
        rows.append(
            {
                "alert_status": "paper_review_ready" if ready else "not_ready",
                "symbol": row.get("symbol", ""),
                "setup": row.get("setup", ""),
                "direction": row.get("direction", ""),
                "signal_time_et": row.get("latest_signal_et", ""),
                "entry": row.get("planned_entry", ""),
                "stop": row.get("planned_stop", ""),
                "target": row.get("planned_target", ""),
                "shares": size.get("suggested_shares", ""),
                "estimated_risk_dollars": size.get("estimated_risk_dollars", ""),
                "scanner_status": row.get("scanner_status", ""),
                "signal_freshness": row.get("signal_freshness", ""),
                "sizing_status": size.get("sizing_status", "missing"),
                "next_action": (
                    "Review checklist, then run local paper confirm if every item passes."
                    if ready
                    else "Wait. Do not confirm local paper execution."
                ),
                "blockers": "; ".join(blockers),
            }
        )

    return pd.DataFrame(rows, columns=ALERT_COLUMNS)


def write_report(path: Path, alerts: pd.DataFrame) -> None:
    """Write the alert Markdown report."""

    ready = alerts[alerts["alert_status"] == "paper_review_ready"] if not alerts.empty else pd.DataFrame()
    not_ready = alerts[alerts["alert_status"] != "paper_review_ready"] if not alerts.empty else pd.DataFrame()
    if ready.empty:
        verdict = "No paper candidate is ready for review."
        confirm_command = "Do not run the local paper confirm command yet."
    else:
        verdict = f"{len(ready)} paper candidate(s) are ready for checklist review."
        confirm_command = ".venv/bin/python run_paper_execution_simulator.py --confirm-local-paper"

    path.write_text(
        f"""# Paper Candidate Alerts

This report highlights current-candle paper candidates that are ready for
manual review.

Important: this is research and paper-validation only. It does not place
orders, create broker alerts, call Webull order endpoints, or connect to broker
execution.

## Verdict

```text
{verdict}
```

## Ready For Paper Review

{markdown_table(ready)}

## Not Ready / Blocked Current Candidates

{markdown_table(not_ready)}

## Confirm Command

```text
{confirm_command}
```

## Required Human Checks

- [ ] Current-candle signal is still valid.
- [ ] Scanner status is allowed.
- [ ] Sizing status is size_ok.
- [ ] Entry, stop, target, and shares match the dashboard.
- [ ] Stop is accepted before entry.
- [ ] No event/news reason to skip.
- [ ] This is local paper simulation only.
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scanner = read_csv_or_empty(args.output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(args.output_dir / "position_sizing.csv")
    alerts = build_alert_rows(scanner, sizing, market_refresh_state())

    csv_path = args.output_dir / "paper_candidate_alerts.csv"
    report_path = args.output_dir / "paper_candidate_alerts.md"
    alerts.to_csv(csv_path, index=False)
    write_report(report_path, alerts)

    ready_count = int((alerts["alert_status"] == "paper_review_ready").sum()) if not alerts.empty else 0
    print(f"Paper candidates ready for review: {ready_count}")
    print(f"Saved candidate alerts CSV: {csv_path}")
    print(f"Saved candidate alerts report: {report_path}")


if __name__ == "__main__":
    main()

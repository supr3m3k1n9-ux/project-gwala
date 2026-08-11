"""Write Project Gwala refresh readiness reports.

This command tells the user whether Webull data refresh is currently allowed,
what command to run next, and whether paper import should remain blocked.

It does not fetch data, place orders, create alerts, or connect to broker
execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from reports.refresh_status import build_refresh_status
from run_playbook import markdown_table


RECOMMENDATION_CHECKLIST = [
    "Run refresh only during regular market hours.",
    "Keep paper import blocked until current-candle candidates exist after refresh.",
    "Review setup health before trusting any approved setup.",
    "Keep logs/system_state.json as the app source of truth.",
    "Continue paper validation toward the 30-trade checkpoint.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build refresh readiness status.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def write_markdown(path: Path, status: dict) -> None:
    """Write a readable Markdown refresh status report."""

    csvs = pd.DataFrame(status["webull_csvs"])
    checklist = "\n".join(f"- [ ] {item}" for item in RECOMMENDATION_CHECKLIST)

    summary = pd.DataFrame(
        [
            {"field": "status", "value": status["status"]},
            {"field": "reason", "value": status["reason"]},
            {"field": "next_action", "value": status["next_action"]},
            {"field": "paper_import_blocked", "value": status["paper_import_blocked"]},
            {"field": "paper_import_reason", "value": status["paper_import_reason"]},
            {"field": "refresh_command", "value": status["refresh_command"]},
        ]
    )
    market = pd.DataFrame([status["market"]])
    scanner = pd.DataFrame([status["scanner"]])
    candles = pd.DataFrame([status.get("candle_freshness", {})])
    provider = pd.DataFrame([status.get("provider_refresh", {})])

    path.write_text(
        f"""# Refresh Status

This report tells you whether Project Gwala is ready to refresh Webull data and
whether paper import should stay blocked.

Important: this is research/paper workflow only. It does not fetch data, place
orders, create alerts, or connect to broker execution.

## Verdict

```text
{status["next_action"]}
```

## Summary

{markdown_table(summary)}

## Market

{markdown_table(market)}

## Scanner

{markdown_table(scanner)}

## Candle Freshness

{markdown_table(candles)}

## Provider Refresh

{markdown_table(provider)}

## Approved Symbol CSV State

{markdown_table(csvs)}

## Recommendation Checklist

{checklist}

## Files

```text
logs/refresh_status.json
logs/refresh_status.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    status = build_refresh_status(args.output_dir)
    json_path = args.output_dir / "refresh_status.json"
    md_path = args.output_dir / "refresh_status.md"

    json_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    write_markdown(md_path, status)

    print(f"Saved refresh status JSON: {json_path}")
    print(f"Saved refresh status report: {md_path}")


if __name__ == "__main__":
    main()

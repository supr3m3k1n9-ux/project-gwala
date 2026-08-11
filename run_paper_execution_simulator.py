"""Create local paper order tickets from eligible scanner/sizing rows.

This is local paper simulation only. It does not call Webull order endpoints,
does not place Webull paper orders, and does not connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from config.runtime_paths import runtime_data_path
from execution.paper_trader import (
    build_local_paper_orders,
    eligible_sizing_rows,
    filter_new_orders,
    orders_to_open_paper_trades,
    read_orders,
    write_open_paper_trades,
)
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local Project Gwala paper execution simulation.")
    parser.add_argument(
        "--sizing-csv",
        type=Path,
        default=Path("logs/position_sizing.csv"),
        help="Position sizing rows produced by run_position_sizer.py.",
    )
    parser.add_argument(
        "--paper-orders-csv",
        type=Path,
        default=runtime_data_path("paper_orders.csv"),
        help="Local paper order ledger.",
    )
    parser.add_argument(
        "--paper-csv",
        type=Path,
        default=runtime_data_path("paper_trades.csv"),
        help="Paper trade log to append open simulated trades to.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where preview reports are saved.")
    parser.add_argument(
        "--pre-entry-csv",
        type=Path,
        default=Path("logs/pre_entry_review.csv"),
        help="Pre-entry checklist generated before local paper preview.",
    )
    parser.add_argument(
        "--confirm-local-paper",
        action="store_true",
        help="Actually write local paper orders and open paper-trade rows. Defaults to preview only.",
    )
    return parser.parse_args()


def read_sizing(path: Path) -> pd.DataFrame:
    """Read the position sizing file."""

    if not path.exists():
        raise FileNotFoundError(f"Position sizing CSV not found: {path}")
    return pd.read_csv(path)


def read_pre_entry(path: Path) -> pd.DataFrame:
    """Read the pre-entry review file if it exists."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def annotate_pre_entry(eligible: pd.DataFrame, pre_entry: pd.DataFrame) -> pd.DataFrame:
    """Add pre-entry gate status to eligible rows for the preview report."""

    if eligible.empty:
        return eligible
    result = eligible.copy()
    result["pre_entry_status"] = "missing"
    result["pre_entry_blockers"] = "Run python run_pre_entry_review.py before confirming local paper."
    if pre_entry.empty:
        return result
    for index, row in result.iterrows():
        matches = pre_entry[
            (pre_entry["symbol"].astype(str) == str(row.get("symbol", "")))
            & (pre_entry["setup"].astype(str) == str(row.get("setup", "")))
            & (pre_entry["direction"].astype(str) == str(row.get("direction", "")))
        ]
        if matches.empty:
            continue
        review = matches.iloc[0]
        result.loc[index, "pre_entry_status"] = str(review.get("review_status", "missing"))
        result.loc[index, "pre_entry_blockers"] = str(review.get("blockers", ""))
    return result


def write_report(
    path: Path,
    eligible: pd.DataFrame,
    orders: pd.DataFrame,
    written_orders: pd.DataFrame,
    written_trades: pd.DataFrame,
    confirmed: bool,
) -> None:
    """Write a Markdown summary of the local paper execution run."""

    path.write_text(
        f"""# Local Paper Execution Simulator

This report previews or records local paper order tickets from eligible
Project Gwala scanner and position-sizing rows.

Important: this is local paper simulation only. It does not call Webull order
endpoints, place Webull paper orders, create broker alerts, or connect to
broker execution.

## Run Mode

```text
Confirmed write: {confirmed}
```

## Eligible Size Rows

{markdown_table(eligible)}

## Local Paper Orders Built

{markdown_table(orders)}

## Orders Written This Run

{markdown_table(written_orders)}

## Open Paper Trades Written This Run

{markdown_table(written_trades)}

## Output Files

```text
data/paper_orders.csv
data/paper_trades.csv
logs/local_paper_execution_simulator.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    sizing = read_sizing(args.sizing_csv)
    eligible = eligible_sizing_rows(sizing)
    eligible_report = annotate_pre_entry(eligible, read_pre_entry(args.pre_entry_csv))
    built_orders = build_local_paper_orders(eligible)
    existing_orders = read_orders(args.paper_orders_csv)
    new_orders = filter_new_orders(existing_orders, built_orders)

    written_orders = pd.DataFrame(columns=built_orders.columns)
    written_trades = pd.DataFrame()
    if args.confirm_local_paper and not new_orders.empty:
        args.paper_orders_csv.parent.mkdir(parents=True, exist_ok=True)
        combined_orders = pd.concat([existing_orders, new_orders], ignore_index=True)
        combined_orders.to_csv(args.paper_orders_csv, index=False)
        written_orders = new_orders

        open_trades = orders_to_open_paper_trades(new_orders)
        written_trades = write_open_paper_trades(args.paper_csv, open_trades)

    report_path = args.output_dir / "local_paper_execution_simulator.md"
    write_report(report_path, eligible_report, built_orders, written_orders, written_trades, args.confirm_local_paper)

    print(f"Eligible local paper rows: {len(eligible)}")
    print(f"New local paper orders: {len(new_orders)}")
    if args.confirm_local_paper:
        print(f"Orders written: {len(written_orders)}")
        print(f"Open paper trades written: {len(written_trades)}")
    else:
        print("Preview only. Add --confirm-local-paper to write local paper orders.")
    print(f"Saved report: {report_path}")


if __name__ == "__main__":
    main()

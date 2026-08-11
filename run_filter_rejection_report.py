"""Build a ship-mode filter rejection report.

This report explains why candidates are not reaching the paper gate. It keeps
safety-critical filters strict, labels trade-quality filters as tunable, and
marks experimental filters so they can stay disabled by default.

Research and paper workflow only. No broker orders or live execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from config.filter_policy import (
    DEFAULT_PAPER_TRADE_FILTER,
    EXPERIMENTAL_FILTERS_ENABLED_BY_DEFAULT,
    OPTIONS_CONTRACT_THRESHOLDS,
    PAPER_GATE_THRESHOLDS,
    classify_filter_reason,
    filter_catalog_records,
)
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build filter rejection report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def text(value: object) -> str:
    """Return stable text for reports."""

    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def split_semicolon(value: object) -> list[str]:
    """Split semicolon-separated rejection text."""

    return [item.strip() for item in text(value).split(";") if item.strip()]


def split_blockers(value: object) -> list[str]:
    """Split pre-entry blocker sentences without losing router detail."""

    raw = text(value)
    if not raw:
        return []
    if "Market regime router says" in raw:
        head, _, tail = raw.partition("Market regime router says")
        pieces = [piece.strip() for piece in head.split(".") if piece.strip()]
        pieces.append(f"Market regime router says {tail.strip()}")
        return pieces
    return [piece.strip() for piece in raw.split(".") if piece.strip()]


def row_identity(row: pd.Series) -> str:
    """Return a stable identity for one candidate row."""

    parts = [
        text(row.get("scan_date")),
        text(row.get("latest_signal_et")) or text(row.get("signal_time_et")) or text(row.get("latest_candle_et")),
        text(row.get("symbol")).upper(),
        text(row.get("setup")),
        text(row.get("direction")),
        text(row.get("variant")),
        text(row.get("exit_profile")),
    ]
    return "|".join(parts)


def add_event(events: list[dict[str, object]], stage: str, source: str, row: pd.Series, reason: object) -> None:
    """Append one classified rejection event."""

    reason_text = text(reason)
    if not reason_text:
        return
    classified = classify_filter_reason(reason_text, stage)
    events.append(
        {
            "stage": stage,
            "source_file": source,
            "candidate_id": row_identity(row),
            "symbol": text(row.get("symbol")).upper(),
            "setup": text(row.get("setup")),
            "direction": text(row.get("direction")),
            "variant": text(row.get("variant")),
            "exit_profile": text(row.get("exit_profile")),
            "filter_id": classified["filter_id"],
            "category": classified["category"],
            "family": classified["family"],
            "reason": classified["normalized_reason"],
        }
    )


def scanner_events(output_dir: Path, events: list[dict[str, object]]) -> None:
    """Collect scanner-level filter rejections."""

    path = output_dir / "daily_paper_signal_scanner.csv"
    scanner = read_csv_or_empty(path)
    if scanner.empty:
        return
    for _, row in scanner.iterrows():
        status = text(row.get("scanner_status"))
        if status == "data_error":
            add_event(events, "scanner", path.name, row, row.get("latest_candle_notes"))
        if text(row.get("block_reason")):
            add_event(events, "scanner", path.name, row, row.get("block_reason"))
        if status == "not_ready":
            for reason in split_semicolon(row.get("missing_conditions")):
                add_event(events, "scanner", path.name, row, reason)


def sizing_events(output_dir: Path, events: list[dict[str, object]]) -> None:
    """Collect position-sizing filter rejections."""

    path = output_dir / "position_sizing.csv"
    sizing = read_csv_or_empty(path)
    if sizing.empty or "sizing_status" not in sizing.columns:
        return
    for _, row in sizing.iterrows():
        if text(row.get("sizing_status")) != "size_ok":
            add_event(events, "position_sizing", path.name, row, row.get("sizing_reason") or row.get("sizing_status"))


def pre_entry_events(output_dir: Path, events: list[dict[str, object]]) -> None:
    """Collect pre-entry review blockers."""

    path = output_dir / "pre_entry_review.csv"
    review = read_csv_or_empty(path)
    if review.empty or "review_status" not in review.columns:
        return
    for _, row in review.iterrows():
        if text(row.get("review_status")) != "ready_for_manual_review":
            for reason in split_blockers(row.get("blockers")):
                add_event(events, "pre_entry", path.name, row, reason)


def router_events(output_dir: Path, events: list[dict[str, object]]) -> None:
    """Collect market-regime router blockers."""

    path = output_dir / "market_regime_router_candidates.csv"
    router = read_csv_or_empty(path)
    if router.empty or "candidate_route" not in router.columns:
        return
    allowed_routes = {"review_first", "unrouted"}
    for _, row in router.iterrows():
        route = text(row.get("candidate_route"))
        if route and route not in allowed_routes:
            add_event(events, "market_regime_router", path.name, row, f"{route}: {text(row.get('action'))}")


def paper_gate_events(output_dir: Path, events: list[dict[str, object]]) -> None:
    """Collect Paper Gate v2 blockers."""

    path = output_dir / "paper_gate_v2.csv"
    gate = read_csv_or_empty(path)
    if gate.empty or "sample_status" not in gate.columns:
        return
    for _, row in gate.iterrows():
        if text(row.get("sample_status")) == "ready_for_validation_sample":
            continue
        for reason in split_semicolon(row.get("guardrail_blockers")):
            add_event(events, "paper_gate", path.name, row, reason)
        reason = text(row.get("reason"))
        if reason and not reason.startswith("Hard safety gate failed"):
            add_event(events, "paper_gate", path.name, row, reason)
        for reason in split_semicolon(row.get("missing_conditions")):
            add_event(events, "paper_gate", path.name, row, reason)


def contract_events(output_dir: Path, events: list[dict[str, object]]) -> None:
    """Collect Options Contract Gate blockers."""

    path = output_dir / "options_contract_gate.csv"
    gate = read_csv_or_empty(path)
    if gate.empty or "contract_gate_status" not in gate.columns:
        return
    for _, row in gate.iterrows():
        if str(row.get("contract_gate_pass", "")).lower() == "true":
            continue
        for reason in split_semicolon(row.get("contract_gate_reason")):
            add_event(events, "options_contract_gate", path.name, row, reason)


def build_events(output_dir: Path) -> pd.DataFrame:
    """Build all rejection event rows."""

    events: list[dict[str, object]] = []
    scanner_events(output_dir, events)
    sizing_events(output_dir, events)
    pre_entry_events(output_dir, events)
    router_events(output_dir, events)
    paper_gate_events(output_dir, events)
    contract_events(output_dir, events)
    return pd.DataFrame(events)


def build_summary(events: pd.DataFrame) -> pd.DataFrame:
    """Return counts by stage and normalized filter."""

    if events.empty:
        return pd.DataFrame(columns=["category", "family", "filter_id", "stage", "rejections", "candidates"])
    return (
        events.groupby(["category", "family", "filter_id", "stage"], dropna=False)
        .agg(rejections=("reason", "count"), candidates=("candidate_id", "nunique"))
        .reset_index()
        .sort_values(["category", "rejections", "filter_id"], ascending=[True, False, True])
    )


def build_category_summary(events: pd.DataFrame) -> pd.DataFrame:
    """Return high-level counts by filter category."""

    if events.empty:
        return pd.DataFrame(columns=["category", "rejections", "candidates"])
    return (
        events.groupby("category")
        .agg(rejections=("reason", "count"), candidates=("candidate_id", "nunique"))
        .reset_index()
        .sort_values("rejections", ascending=False)
    )


def write_outputs(output_dir: Path, events: pd.DataFrame, summary: pd.DataFrame, category_summary: pd.DataFrame) -> None:
    """Write CSV and Markdown reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    catalog = pd.DataFrame(filter_catalog_records())
    thresholds = pd.DataFrame(
        [{"scope": "paper_gate", "filter": key, "value": value} for key, value in PAPER_GATE_THRESHOLDS.items()]
        + [
            {"scope": "options_contract_gate", "filter": key, "value": value}
            for key, value in OPTIONS_CONTRACT_THRESHOLDS.items()
        ]
    )

    events.to_csv(output_dir / "filter_rejection_audit.csv", index=False)
    summary.to_csv(output_dir / "filter_rejection_summary.csv", index=False)
    catalog.to_csv(output_dir / "filter_policy_audit.csv", index=False)
    thresholds.to_csv(output_dir / "filter_thresholds.csv", index=False)

    top_events = events.head(80) if not events.empty else events
    (output_dir / "filter_rejection_report.md").write_text(
        f"""# Filter Rejection Report

This report explains which filters are preventing scanner rows from becoming
countable paper trades.

Important: this is research and paper-validation only. It does not place
broker orders, create broker alerts, or enable live execution.

## Ship-Mode Policy

```text
Default paper scanner trade filter: {DEFAULT_PAPER_TRADE_FILTER}
Experimental filters enabled by default: {EXPERIMENTAL_FILTERS_ENABLED_BY_DEFAULT}
Safety-critical filters: strict
Trade-quality filters: configurable thresholds
Experimental filters: disabled by default
```

## Rejections By Category

{markdown_table(category_summary)}

## Rejections By Filter

{markdown_table(summary)}

## Active Thresholds

{markdown_table(thresholds)}

## Filter Catalog

{markdown_table(catalog)}

## Latest Rejection Events

{markdown_table(top_events)}

## Files

```text
logs/filter_rejection_audit.csv
logs/filter_rejection_summary.csv
logs/filter_policy_audit.csv
logs/filter_thresholds.csv
logs/filter_rejection_report.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    events = build_events(args.output_dir)
    summary = build_summary(events)
    category_summary = build_category_summary(events)
    write_outputs(args.output_dir, events, summary, category_summary)
    print(f"Filter rejection events: {len(events)}")
    print(f"Saved filter rejection report: {args.output_dir / 'filter_rejection_report.md'}")


if __name__ == "__main__":
    main()

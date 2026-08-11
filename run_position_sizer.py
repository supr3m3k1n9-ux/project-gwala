"""Create a paper-trade position sizing sheet from scanner candidates.

This is research and paper workflow only. It converts planned entries and stops
into suggested share sizes. It does not place orders, create alerts, or connect
to broker execution.
"""

from __future__ import annotations

import argparse
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.filter_policy import PAPER_GATE_THRESHOLDS
from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_path
from config.runtime_paths import runtime_data_root
from config.settings import ACCOUNT
from reports.refresh_status import market_refresh_state
from run_playbook import markdown_table

VALID_REFRESH_EVIDENCE = {"files_present_and_complete", "current_session_in_progress"}
PAPER_VALIDATION_FRESHNESS = {"current_candle", "grace_candle"}


def default_refresh_audit_csv() -> Path:
    """Return the durable refresh-audit CSV path."""

    return runtime_data_root() / "market_refresh_audit.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Size Project Gwala paper-trade candidates.")
    parser.add_argument(
        "--scanner-csv",
        type=Path,
        default=Path("logs/daily_paper_signal_scanner.csv"),
        help="Daily scanner CSV with planned entries and stops.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where sizing reports are saved.")
    parser.add_argument("--account-size", type=float, default=ACCOUNT.starting_equity, help="Paper account size.")
    parser.add_argument(
        "--risk-per-trade-pct",
        type=float,
        default=ACCOUNT.risk_per_trade_pct,
        help="Account percentage risked per paper trade. 0.005 means 0.5%%.",
    )
    parser.add_argument(
        "--max-daily-loss-r",
        type=float,
        default=-3.0,
        help="Stop taking new paper trades once daily realized R is at or below this value.",
    )
    parser.add_argument(
        "--max-monthly-loss-r",
        type=float,
        default=-3.0,
        help="Stop taking new paper trades once monthly realized R is at or below this value.",
    )
    parser.add_argument(
        "--paper-csv",
        type=Path,
        default=runtime_data_path("paper_trades.csv"),
        help="Paper trade log used to derive realized loss-stop R.",
    )
    parser.add_argument(
        "--refresh-audit-csv",
        type=Path,
        default=default_refresh_audit_csv(),
        help="Refresh evidence required before an actionable paper size.",
    )
    parser.add_argument("--daily-realized-r", type=float, default=None, help="Optional override for today's realized paper R.")
    parser.add_argument("--monthly-realized-r", type=float, default=None, help="Optional override for this month's realized paper R.")
    parser.add_argument(
        "--freshness",
        choices=["paper_validation", "current_candle", "grace_candle", "earlier_today", "all"],
        default="paper_validation",
        help="Which scanner candidates are eligible for sizing.",
    )
    parser.add_argument(
        "--include-watch-only",
        action="store_true",
        help="Also size blocked/watch-only signals for study. They remain watch-only.",
    )
    return parser.parse_args()


def read_scanner(path: Path) -> pd.DataFrame:
    """Read the scanner CSV."""

    if not path.exists():
        raise FileNotFoundError(f"Scanner CSV not found: {path}")
    return pd.read_csv(path)


def numeric(value: object) -> float | None:
    """Convert CSV values to numbers when possible."""

    if pd.isna(value) or str(value).strip() == "":
        return None
    return float(value)


def realized_r_from_paper_log(path: Path, now: datetime | None = None) -> tuple[float, float]:
    """Calculate allowed completed paper R for today's and this month's risk stops."""

    if not path.exists():
        return 0.0, 0.0
    trades = pd.read_csv(path)
    required = {"trade_date", "signal_status", "outcome_r"}
    if trades.empty or not required.issubset(trades.columns):
        return 0.0, 0.0

    now = now or datetime.now(MARKET_TZ)
    local = now.astimezone(MARKET_TZ)
    completed = trades[trades["signal_status"] == "allowed"].copy()
    if "invalid_for_validation" in completed.columns:
        invalid = completed["invalid_for_validation"].astype(str).str.lower().isin(["1", "true", "yes", "y"])
        completed = completed[~invalid].copy()
    completed["outcome_r"] = pd.to_numeric(completed["outcome_r"], errors="coerce")
    completed = completed.dropna(subset=["outcome_r"])
    completed["trade_date"] = completed["trade_date"].astype(str)
    daily = completed.loc[completed["trade_date"] == local.date().isoformat(), "outcome_r"].sum()
    monthly = completed.loc[completed["trade_date"].str.startswith(local.strftime("%Y-%m")), "outcome_r"].sum()
    return round(float(daily), 4), round(float(monthly), 4)


def resolve_realized_r(args: argparse.Namespace, now: datetime | None = None) -> None:
    """Use paper-log totals unless explicit test/research overrides were supplied."""

    daily, monthly = realized_r_from_paper_log(args.paper_csv, now)
    if args.daily_realized_r is None:
        args.daily_realized_r = daily
    if args.monthly_realized_r is None:
        args.monthly_realized_r = monthly


def risk_status(row: pd.Series, args: argparse.Namespace) -> tuple[str, str]:
    """Decide whether a scanner row is eligible for paper sizing."""

    watch_only_study = False
    if row["scanner_status"] == "blocked_watch_only":
        if not args.include_watch_only:
            return "watch_only", "Blocked by research filter; not sized by default."
        watch_only_study = True
    elif row["scanner_status"] != "allowed":
        return "not_allowed", "Scanner did not mark this setup as allowed."

    freshness = str(row.get("signal_freshness", ""))
    if args.freshness == "paper_validation":
        if freshness not in PAPER_VALIDATION_FRESHNESS:
            return "not_current", f"Signal freshness is {freshness}, not current_candle or grace_candle."
    elif args.freshness != "all" and freshness != args.freshness:
        return "not_current", f"Signal freshness is {freshness}, not {args.freshness}."

    if args.daily_realized_r <= args.max_daily_loss_r:
        return "daily_stop_hit", "Daily loss limit has been reached."

    if args.monthly_realized_r <= args.max_monthly_loss_r:
        return "monthly_stop_hit", "Monthly loss limit has been reached."

    entry = numeric(row.get("planned_entry"))
    stop = numeric(row.get("planned_stop"))
    risk_per_share = numeric(row.get("risk_per_share"))
    if entry is None or stop is None or risk_per_share is None:
        return "missing_plan", "No valid planned entry, stop, or risk per share."

    if risk_per_share <= 0:
        return "bad_risk", "Risk per share must be greater than zero."

    if watch_only_study:
        return "watch_only_study", "Study size only; blocked/watch-only signals are not paper-trade candidates."
    if freshness == "grace_candle":
        return "size_ok", "Eligible for reduced B-tier grace paper sizing."
    return "size_ok", "Eligible for paper sizing."


def risk_pct_for_row(row: pd.Series, args: argparse.Namespace) -> float:
    """Return the paper-validation risk percentage for a scanner row."""

    if str(row.get("signal_freshness", "")) == "grace_candle":
        return min(float(args.risk_per_trade_pct), float(PAPER_GATE_THRESHOLDS["b_risk_pct"]))
    return float(args.risk_per_trade_pct)


def size_row(row: pd.Series, args: argparse.Namespace) -> dict:
    """Create one position-sizing row."""

    status, reason = risk_status(row, args)
    applied_risk_pct = risk_pct_for_row(row, args)
    risk_budget = args.account_size * applied_risk_pct
    entry = numeric(row.get("planned_entry"))
    risk_per_share = numeric(row.get("risk_per_share"))

    shares = 0
    estimated_risk = 0.0
    notional = 0.0
    if status in {"size_ok", "watch_only_study"} and entry is not None and risk_per_share is not None:
        shares = math.floor(risk_budget / risk_per_share)
        if shares < 1:
            status = "too_wide"
            reason = "Stop is too wide for the selected account risk."
        else:
            estimated_risk = shares * risk_per_share
            notional = shares * entry

    return {
        "symbol": row.get("symbol", ""),
        "setup": row.get("setup", ""),
        "direction": row.get("direction", ""),
        "validation_lane": row.get("validation_lane", ""),
        "scanner_status": row.get("scanner_status", ""),
        "signal_freshness": row.get("signal_freshness", ""),
        "latest_signal_et": row.get("latest_signal_et", ""),
        "candidate_entry_et": row.get("candidate_entry_et", row.get("latest_signal_et", "")),
        "planned_entry": row.get("planned_entry", ""),
        "planned_stop": row.get("planned_stop", ""),
        "planned_target": row.get("planned_target", ""),
        "risk_per_share": row.get("risk_per_share", ""),
        "account_size": round(args.account_size, 2),
        "risk_per_trade_pct": round(applied_risk_pct, 4),
        "risk_budget_dollars": round(risk_budget, 2),
        "suggested_shares": shares,
        "estimated_risk_dollars": round(estimated_risk, 2),
        "estimated_notional": round(notional, 2),
        "sizing_status": status,
        "sizing_reason": reason,
    }


def build_sizing(scanner: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    """Build the sizing sheet from all scanner rows."""

    rows = [size_row(row, args) for _, row in scanner.iterrows()]
    return pd.DataFrame(rows).sort_values(["sizing_status", "symbol", "setup"])


def apply_session_gate(
    sizing: pd.DataFrame,
    scanner: pd.DataFrame,
    market: dict,
    refresh_audit: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Block actionable paper sizing unless scanner evidence is current and the market is open."""

    if sizing.empty or "sizing_status" not in sizing.columns:
        return sizing
    result = sizing.copy()
    actionable = result["sizing_status"] == "size_ok"
    earlier_rows = actionable & ~result["signal_freshness"].astype(str).isin(PAPER_VALIDATION_FRESHNESS)
    result.loc[earlier_rows, "sizing_status"] = "not_current"
    result.loc[earlier_rows, "sizing_reason"] = "Signals outside current_candle or one-M30 grace are study-only."
    result.loc[earlier_rows, "suggested_shares"] = 0
    result.loc[earlier_rows, "estimated_risk_dollars"] = 0.0
    result.loc[earlier_rows, "estimated_notional"] = 0.0

    scanner_dates = {str(value) for value in scanner.get("scan_date", pd.Series(dtype=str)).dropna().unique()}
    gate_open = market["market_is_open"] and scanner_dates == {market["today"]}
    if gate_open:
        actionable = result["sizing_status"] == "size_ok"
        if not actionable.any():
            return result
        audit = refresh_audit.copy() if refresh_audit is not None else pd.DataFrame()
        required = {"symbol", "m30_latest_session", "m5_latest_session", "refresh_evidence_status"}
        if required.issubset(audit.columns):
            valid_audit = audit[
                (audit["m30_latest_session"].astype(str) == market["today"])
                & (audit["m5_latest_session"].astype(str) == market["today"])
                & (audit["refresh_evidence_status"].isin(VALID_REFRESH_EVIDENCE))
            ]
            audited_symbols = set(valid_audit["symbol"].astype(str).str.upper())
        else:
            audited_symbols = set()
        missing_audit = actionable & ~result["symbol"].astype(str).str.upper().isin(audited_symbols)
        result.loc[missing_audit, "sizing_status"] = "not_refreshed_session"
        result.loc[missing_audit, "sizing_reason"] = (
            "Sizing blocked until current-session Webull refresh evidence is recorded for this symbol."
        )
        result.loc[missing_audit, "suggested_shares"] = 0
        result.loc[missing_audit, "estimated_risk_dollars"] = 0.0
        result.loc[missing_audit, "estimated_notional"] = 0.0
        return result

    actionable = result["sizing_status"] == "size_ok"
    result.loc[actionable, "sizing_status"] = "not_current_session"
    result.loc[actionable, "sizing_reason"] = (
        "Sizing blocked until scanner data is refreshed during today's open market session."
    )
    result.loc[actionable, "suggested_shares"] = 0
    result.loc[actionable, "estimated_risk_dollars"] = 0.0
    result.loc[actionable, "estimated_notional"] = 0.0
    return result


def write_report(path: Path, sizing: pd.DataFrame, args: argparse.Namespace) -> None:
    """Write the Markdown sizing report."""

    eligible = sizing[sizing["sizing_status"] == "size_ok"]
    blocked = sizing[sizing["sizing_status"] != "size_ok"]
    status_counts = sizing.groupby("sizing_status").size().reset_index(name="setups")

    path.write_text(
        f"""# Paper Position Sizing

This report turns scanner candidates into paper-trade share sizes.

Important: this is research/paper workflow only. It does not place orders,
create alerts, or connect to broker execution.

## Settings

```text
Account size: ${args.account_size:,.2f}
Risk per trade: {args.risk_per_trade_pct:.4f}
Risk budget: ${args.account_size * args.risk_per_trade_pct:,.2f}
Daily realized R: {args.daily_realized_r}
Monthly realized R: {args.monthly_realized_r}
Max daily loss R: {args.max_daily_loss_r}
Max monthly loss R: {args.max_monthly_loss_r}
Freshness filter: {args.freshness}
Include watch-only: {args.include_watch_only}
```

## Status Counts

{markdown_table(status_counts)}

## Eligible Paper Sizes

{markdown_table(eligible)}

## Not Sized

{markdown_table(blocked)}

## Files

```text
logs/position_sizing.csv
logs/position_sizing.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    resolve_realized_r(args)

    scanner = read_scanner(args.scanner_csv)
    sizing = build_sizing(scanner, args)
    refresh_audit = pd.read_csv(args.refresh_audit_csv) if args.refresh_audit_csv.exists() else pd.DataFrame()
    sizing = apply_session_gate(sizing, scanner, market_refresh_state(), refresh_audit)

    csv_path = args.output_dir / "position_sizing.csv"
    report_path = args.output_dir / "position_sizing.md"
    sizing.to_csv(csv_path, index=False)
    write_report(report_path, sizing, args)

    print(f"Saved position sizing CSV: {csv_path}")
    print(f"Saved position sizing report: {report_path}")


if __name__ == "__main__":
    main()

"""Repair stale M30 candles from fresher Webull lower-timeframe candles.

This is a data-quality guardrail for the local research/paper workflow. It
does not fetch market data, import paper trades, place orders, or connect to a
broker. It only reconciles a local cache mismatch when Webull returns current
M5 candles but leaves an M30 file behind on a prior session.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.symbol_playbook import playbook_symbols
from data.candle_cache import preferred_candle_path, save_candle_cache
from data.market_data import REQUIRED_CSV_COLUMNS
from data.market_data_sources import append_sources, source_row
from run_playbook import markdown_table


PROVIDER = "webull_derived_m5_to_m30"


@dataclass(frozen=True)
class RepairResult:
    """Outcome for one symbol repair attempt."""

    symbol: str
    status: str
    source_latest_et: str
    target_before_et: str
    target_after_et: str
    derived_rows_added: int
    message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair stale M30 cache rows from fresher M5 candles.")
    parser.add_argument("--symbols", nargs="+", default=playbook_symbols("approved_plus_watch"))
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where candle CSVs live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where repair reports are saved.")
    parser.add_argument("--source-timeframe", default="M5")
    parser.add_argument("--target-timeframe", default="M30")
    return parser.parse_args()


def normalized_candles(path: Path) -> pd.DataFrame:
    """Load candle CSV rows into a UTC-indexed OHLCV frame."""

    raw = pd.read_csv(path)
    missing = [column for column in REQUIRED_CSV_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(f"{path} is missing required column(s): {', '.join(missing)}")

    candles = raw[REQUIRED_CSV_COLUMNS].copy()
    candles["datetime"] = pd.to_datetime(candles["datetime"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        candles[column] = pd.to_numeric(candles[column], errors="coerce")
    candles = candles.dropna(subset=REQUIRED_CSV_COLUMNS)
    if candles.empty:
        raise ValueError(f"No valid candles found in {path}.")
    candles = candles.sort_values("datetime").drop_duplicates("datetime", keep="last")
    return candles.set_index("datetime")


def latest_et(candles: pd.DataFrame) -> str:
    """Return the latest candle timestamp in market time for display."""

    if candles.empty:
        return ""
    latest = candles.index.max().tz_convert(MARKET_TZ)
    return latest.strftime("%Y-%m-%d %H:%M")


def candles_to_csv_frame(candles: pd.DataFrame) -> pd.DataFrame:
    """Return a browser/app-compatible candle CSV frame."""

    output = candles.sort_index().reset_index()
    output["datetime"] = output["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%S.000%z")
    return output[REQUIRED_CSV_COLUMNS]


def derive_m30_from_lower(source: pd.DataFrame) -> pd.DataFrame:
    """Resample lower-timeframe regular-session candles into M30 bars."""

    local = source.copy()
    local.index = local.index.tz_convert(MARKET_TZ)
    regular = local.between_time("09:30", "15:59")
    if regular.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    derived = regular.resample(
        "30min",
        origin="start_day",
        offset="9h30min",
        label="left",
        closed="left",
    ).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    derived = derived.dropna(subset=["open", "high", "low", "close"])
    derived.index = derived.index.tz_convert("UTC")
    return derived


def merge_repaired_target(target: pd.DataFrame, derived: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Merge target M30 rows with derived rows and count new/overwritten rows."""

    if derived.empty:
        return target, 0
    before_latest = target.index.max() if not target.empty else pd.Timestamp.min.tz_localize("UTC")
    useful = derived[derived.index > before_latest]
    if useful.empty:
        return target, 0
    combined = pd.concat([target, useful]).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined, int(len(useful))


def repair_symbol(symbol: str, data_dir: Path, source_timeframe: str, target_timeframe: str) -> tuple[RepairResult, pd.DataFrame | None, Path | None]:
    """Repair one symbol if lower-timeframe candles are ahead of M30."""

    source_path = preferred_candle_path(data_dir, symbol, source_timeframe)
    target_path = preferred_candle_path(data_dir, symbol, target_timeframe)
    if not source_path.exists():
        return RepairResult(symbol, "skipped", "", "", "", 0, f"Missing {source_timeframe} source."), None, None
    if not target_path.exists():
        return RepairResult(symbol, "skipped", "", "", "", 0, f"Missing {target_timeframe} target."), None, None

    source = normalized_candles(source_path)
    target = normalized_candles(target_path)
    source_latest = latest_et(source)
    before_latest = latest_et(target)
    derived = derive_m30_from_lower(source)
    repaired, rows_added = merge_repaired_target(target, derived)

    if rows_added <= 0:
        return (
            RepairResult(symbol, "current_or_not_repairable", source_latest, before_latest, before_latest, 0, "No newer derived M30 rows."),
            None,
            None,
        )

    output_frame = candles_to_csv_frame(repaired)
    output_path = save_candle_cache(output_frame, data_dir, symbol, target_timeframe, write_legacy_alias=True)
    return (
        RepairResult(
            symbol,
            "repaired",
            source_latest,
            before_latest,
            latest_et(repaired),
            rows_added,
            f"Derived {rows_added} {target_timeframe} row(s) from {source_timeframe}.",
        ),
        output_frame,
        output_path,
    )


def write_reports(output_dir: Path, results: list[RepairResult]) -> None:
    """Write repair reports for dashboard/debugging visibility."""

    rows = [result.__dict__ for result in results]
    frame = pd.DataFrame(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_dir / "m30_repair_audit.csv", index=False)
    (output_dir / "m30_repair_audit.md").write_text(
        f"""# M30 Repair Audit

This local guardrail reconciles stale Webull M30 cache rows from fresher lower
timeframe candles. It does not fetch data or create trades.

{markdown_table(frame)}
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    results: list[RepairResult] = []
    source_rows: list[dict[str, object]] = []
    refreshed_at = datetime.now(MARKET_TZ)

    for symbol in [value.upper() for value in args.symbols]:
        result, repaired, output_path = repair_symbol(symbol, args.data_dir, args.source_timeframe, args.target_timeframe)
        results.append(result)
        if result.status == "repaired" and repaired is not None and output_path is not None:
            dates = pd.to_datetime(repaired["datetime"], utc=True, errors="coerce").dropna()
            source_rows.append(
                source_row(
                    provider=PROVIDER,
                    symbol=symbol,
                    timeframe=args.target_timeframe,
                    candle_path=output_path,
                    candles=repaired,
                    start_date=str(dates.iloc[0].tz_convert(MARKET_TZ).date()) if not dates.empty else "",
                    end_date=str(dates.iloc[-1].tz_convert(MARKET_TZ).date()) if not dates.empty else "",
                    status="ok",
                    message=result.message,
                    refreshed_at=refreshed_at,
                )
            )

    if source_rows:
        append_sources(args.output_dir / "market_data_sources.csv", source_rows)
    write_reports(args.output_dir, results)

    repaired_count = sum(1 for result in results if result.status == "repaired")
    print(f"M30 repair complete. Repaired symbols: {repaired_count}")
    print(f"Saved repair audit: {args.output_dir / 'm30_repair_audit.md'}")


if __name__ == "__main__":
    main()

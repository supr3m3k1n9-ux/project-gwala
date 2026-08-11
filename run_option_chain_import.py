"""Import current option-chain data for A-tier paper candidates.

This command only fills the local option-chain CSV dependency used by
run_options_chain_review.py. It does not select contracts, approve contracts,
place orders, create alerts, or change Contract Gate thresholds.
"""

from __future__ import annotations

import argparse
from datetime import datetime, time
import json
import math
from pathlib import Path
import shutil
from typing import Any

import pandas as pd

from config.filter_policy import OPTIONS_CONTRACT_THRESHOLDS
from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_path
from reports.refresh_status import market_refresh_state
from run_paper_gate_v2 import build_payload as build_paper_gate_payload
from run_playbook import markdown_table


CHAIN_COLUMNS = [
    "contract_symbol",
    "option_type",
    "expiration",
    "dte",
    "strike",
    "delta",
    "bid",
    "ask",
    "mid",
    "spread_pct",
    "volume",
    "open_interest",
    "implied_volatility",
    "premium",
    "earnings_within_window",
    "provider",
    "trading_session_date",
    "chain_retrieval_timestamp",
    "quote_timestamp",
    "underlying_price",
    "underlying_price_timestamp",
    "delta_source",
    "delta_model_name",
    "risk_free_rate",
    "implied_volatility_source",
    "underlying_price_for_delta",
    "calculation_timestamp",
]
RISK_FREE_RATE = 0.04
DELTA_MODEL_NAME = "black_scholes"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import option-chain CSVs for A-tier paper candidates.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--chain-dir", type=Path, default=runtime_data_path("options_chains", "active"))
    parser.add_argument("--samples-csv", type=Path, default=runtime_data_path("paper_validation_samples.csv"))
    parser.add_argument("--candidate-ledger-csv", type=Path, default=runtime_data_path("candidate_window_ledger.csv"))
    parser.add_argument("--account-size", type=float, default=10_000.0)
    parser.add_argument("--max-dte", type=float, default=OPTIONS_CONTRACT_THRESHOLDS["max_dte"])
    parser.add_argument("--provider", choices=["yfinance"], default="yfinance")
    return parser.parse_args()


def text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    raw = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def dte_for_expiration(expiration: str, today: str) -> int | None:
    exp = pd.to_datetime(expiration, errors="coerce")
    now = pd.to_datetime(today, errors="coerce")
    if pd.isna(exp) or pd.isna(now):
        return None
    return int((exp.date() - now.date()).days)


def years_to_expiration(expiration: str, now: datetime) -> float:
    exp_date = pd.to_datetime(expiration, errors="coerce")
    if pd.isna(exp_date):
        return 1.0 / 365.0
    expiry_close = datetime.combine(exp_date.date(), time(16, 0), tzinfo=MARKET_TZ)
    seconds = max((expiry_close - now.astimezone(MARKET_TZ)).total_seconds(), 60.0 * 30.0)
    return seconds / (365.0 * 24.0 * 60.0 * 60.0)


def iso_now(now: datetime) -> str:
    return now.astimezone(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


def metadata_path_for(chain_path: Path) -> Path:
    return chain_path.with_suffix(".metadata.json")


def archive_active_file(path: Path, *, session_date: str, timestamp: datetime) -> None:
    if not path.exists():
        return
    archive_dir = path.parent.parent / "archive" / session_date
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp.astimezone(MARKET_TZ).strftime("%H%M%S")
    shutil.move(str(path), str(archive_dir / f"{path.stem}_{stamp}{path.suffix}"))


def archive_active_chain(path: Path, *, session_date: str, timestamp: datetime) -> None:
    archive_active_file(path, session_date=session_date, timestamp=timestamp)
    archive_active_file(metadata_path_for(path), session_date=session_date, timestamp=timestamp)


def model_delta(*, option_type: str, underlying: float, strike: float, iv: float | None, expiration: str, now: datetime) -> float | None:
    """Return Black-Scholes delta when the chain provider does not include Greeks."""

    if underlying <= 0 or strike <= 0:
        return None
    sigma = iv if iv is not None and iv > 0 else 0.35
    t = years_to_expiration(expiration, now)
    if sigma <= 0 or t <= 0:
        return None
    d1 = (math.log(underlying / strike) + (RISK_FREE_RATE + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    call_delta = norm_cdf(d1)
    return round(call_delta if option_type == "CALL" else call_delta - 1.0, 4)


def ready_a_tier_samples(
    *,
    output_dir: Path,
    samples_csv: Path,
    candidate_ledger_csv: Path,
    account_size: float,
) -> list[dict[str, Any]]:
    paper_gate = build_paper_gate_payload(
        output_dir=output_dir,
        scanner_csv=output_dir / "daily_paper_signal_scanner.csv",
        samples_csv=samples_csv,
        account_size=account_size,
        promotion_source="candidate_ledger",
        candidate_ledger_csv=candidate_ledger_csv,
    )
    ready = paper_gate.get("ready_samples", []) if isinstance(paper_gate.get("ready_samples", []), list) else []
    return [row for row in ready if text(row.get("sample_tier")).upper() == "A"]


def directions_by_symbol(samples: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for sample in samples:
        symbol = text(sample.get("symbol")).upper()
        direction = text(sample.get("direction")).lower()
        if symbol:
            result.setdefault(symbol, set()).add(direction)
    return result


def yfinance_underlying_price(ticker: Any) -> float | None:
    fast_info = getattr(ticker, "fast_info", {}) or {}
    for key in ["last_price", "lastPrice", "regular_market_price"]:
        price = number(fast_info.get(key) if hasattr(fast_info, "get") else None)
        if price and price > 0:
            return price
    history = ticker.history(period="1d", interval="1m")
    if history is not None and not history.empty:
        close = number(history["Close"].dropna().iloc[-1])
        if close and close > 0:
            return close
    return None


def yfinance_earnings_within_window(ticker: Any, now: datetime, window_days: int = 7) -> bool:
    try:
        calendar = ticker.calendar
    except Exception:
        return False
    if calendar is None:
        return False
    values = []
    if isinstance(calendar, pd.DataFrame):
        values = list(calendar.to_numpy().ravel())
    elif isinstance(calendar, dict):
        values = list(calendar.values())
    for value in values:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize(MARKET_TZ)
        delta_days = (parsed.tz_convert(MARKET_TZ).date() - now.date()).days
        if 0 <= delta_days <= window_days:
            return True
    return False


def normalize_yfinance_side(
    frame: pd.DataFrame,
    *,
    option_type: str,
    expiration: str,
    today: str,
    underlying: float,
    earnings_within_window: bool,
    now: datetime,
) -> list[dict[str, Any]]:
    rows = []
    dte = dte_for_expiration(expiration, today)
    if dte is None:
        return rows
    stamp = iso_now(now)
    for _, raw in frame.iterrows():
        bid = number(raw.get("bid"))
        ask = number(raw.get("ask"))
        strike = number(raw.get("strike"))
        iv = number(raw.get("impliedVolatility"))
        if bid is None or ask is None or bid <= 0 or ask <= 0 or strike is None:
            continue
        delta = model_delta(
            option_type=option_type,
            underlying=underlying,
            strike=strike,
            iv=iv,
            expiration=expiration,
            now=now,
        )
        if delta is None or iv is None or iv <= 0:
            continue
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid if mid > 0 else None
        rows.append(
            {
                "contract_symbol": text(raw.get("contractSymbol")),
                "option_type": option_type,
                "expiration": expiration,
                "dte": dte,
                "strike": strike,
                "delta": delta,
                "bid": bid,
                "ask": ask,
                "mid": round(mid, 4),
                "spread_pct": round(spread_pct, 4) if spread_pct is not None else "",
                "volume": number(raw.get("volume")) or 0,
                "open_interest": number(raw.get("openInterest")) or 0,
                "implied_volatility": iv or "",
                "premium": ask,
                "earnings_within_window": earnings_within_window,
                "provider": "yfinance",
                "trading_session_date": today,
                "chain_retrieval_timestamp": stamp,
                "quote_timestamp": stamp,
                "underlying_price": underlying,
                "underlying_price_timestamp": stamp,
                "delta_source": "modeled_black_scholes",
                "delta_model_name": DELTA_MODEL_NAME,
                "risk_free_rate": RISK_FREE_RATE,
                "implied_volatility_source": "provider_impliedVolatility",
                "underlying_price_for_delta": underlying,
                "calculation_timestamp": stamp,
            }
        )
    return rows


def fetch_yfinance_chain(symbol: str, directions: set[str], *, today: str, max_dte: float, now: datetime) -> pd.DataFrame:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    underlying = yfinance_underlying_price(ticker)
    if underlying is None:
        raise RuntimeError(f"Could not read current underlying price for {symbol}.")
    earnings_warning = yfinance_earnings_within_window(ticker, now)
    rows: list[dict[str, Any]] = []
    expirations = list(getattr(ticker, "options", []) or [])
    for expiration in expirations:
        dte = dte_for_expiration(expiration, today)
        if dte is None or dte < OPTIONS_CONTRACT_THRESHOLDS["min_dte"] or dte > max_dte:
            continue
        chain = ticker.option_chain(expiration)
        if "long" in directions:
            rows.extend(
                normalize_yfinance_side(
                    chain.calls,
                    option_type="CALL",
                    expiration=expiration,
                    today=today,
                    underlying=underlying,
                    earnings_within_window=earnings_warning,
                    now=now,
                )
            )
        if "short" in directions:
            rows.extend(
                normalize_yfinance_side(
                    chain.puts,
                    option_type="PUT",
                    expiration=expiration,
                    today=today,
                    underlying=underlying,
                    earnings_within_window=earnings_warning,
                    now=now,
                )
            )
    return pd.DataFrame(rows, columns=CHAIN_COLUMNS)


def write_chain(path: Path, chain: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chain.to_csv(path, index=False)


def write_metadata(path: Path, *, symbol: str, chain: pd.DataFrame, session_date: str, provider: str, generated_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    first = chain.iloc[0].to_dict() if not chain.empty else {}
    metadata = {
        "provider": provider,
        "symbol": symbol,
        "chain_file": str(path),
        "import_status": "success",
        "trading_session_date": session_date,
        "chain_retrieval_timestamp": text(first.get("chain_retrieval_timestamp")),
        "source_file_generation_timestamp": iso_now(generated_at),
        "underlying_price_used": first.get("underlying_price", ""),
        "underlying_price_timestamp": text(first.get("underlying_price_timestamp")),
        "expirations_queried": sorted(str(value) for value in chain["expiration"].dropna().unique()) if "expiration" in chain else [],
        "delta_source": text(first.get("delta_source")),
        "delta_model_name": text(first.get("delta_model_name")),
        "risk_free_rate_used": first.get("risk_free_rate", ""),
        "implied_volatility_source": text(first.get("implied_volatility_source")),
        "underlying_price_used_for_delta": first.get("underlying_price_for_delta", ""),
        "calculation_timestamp": text(first.get("calculation_timestamp")),
        "row_count": int(len(chain)),
    }
    metadata_path_for(path).write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding="utf-8")


def build_import(
    *,
    output_dir: Path = Path("logs"),
    chain_dir: Path | None = None,
    samples_csv: Path | None = None,
    candidate_ledger_csv: Path | None = None,
    account_size: float = 10_000.0,
    max_dte: float = OPTIONS_CONTRACT_THRESHOLDS["max_dte"],
    provider: str = "yfinance",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    chain_dir = chain_dir or runtime_data_path("options_chains")
    samples_csv = samples_csv or runtime_data_path("paper_validation_samples.csv")
    candidate_ledger_csv = candidate_ledger_csv or runtime_data_path("candidate_window_ledger.csv")
    market = market_refresh_state()
    today = text(market.get("today")) or datetime.now(MARKET_TZ).date().isoformat()
    now = datetime.now(MARKET_TZ)
    samples = ready_a_tier_samples(
        output_dir=output_dir,
        samples_csv=samples_csv,
        candidate_ledger_csv=candidate_ledger_csv,
        account_size=account_size,
    )
    symbols = directions_by_symbol(samples)
    rows = []
    imported = 0
    errors = 0
    for symbol, directions in sorted(symbols.items()):
        path = chain_dir / f"{symbol}.csv"
        archive_active_chain(path, session_date=today, timestamp=now)
        try:
            chain = fetch_yfinance_chain(symbol, directions, today=today, max_dte=max_dte, now=now)
            if chain.empty:
                status = "empty_chain"
            else:
                write_chain(path, chain)
                write_metadata(path, symbol=symbol, chain=chain, session_date=today, provider=provider, generated_at=now)
                imported += 1
                status = "imported"
        except Exception as error:
            chain = pd.DataFrame(columns=CHAIN_COLUMNS)
            errors += 1
            status = "error"
            message = str(error)
        else:
            message = ""
        rows.append(
            {
                "symbol": symbol,
                "directions": ",".join(sorted(directions)),
                "chain_csv": str(path),
                "row_count": int(len(chain)),
                "status": status,
                "message": message,
            }
        )

    status = "ready" if imported else "waiting_for_chain_data"
    if not samples:
        status = "waiting_for_a_tier_candidate"
    elif errors and not imported:
        status = "blocked"
    return {
        "generated_at_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "provider": provider,
        "today": today,
        "ready_a_tier_samples": len(samples),
        "symbols_requested": len(symbols),
        "chains_imported": imported,
        "errors": errors,
        "status": status,
        "columns": CHAIN_COLUMNS,
        "guardrail": (
            "Option-chain import is data-only. It writes local chain CSVs for existing Contract Gate review; "
            "it does not select contracts, change thresholds, create alerts, or place orders."
        ),
        "rows": rows,
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = pd.DataFrame(payload["rows"])
    rows.to_csv(output_dir / "option_chain_import.csv", index=False)
    (output_dir / "option_chain_import.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    summary = pd.DataFrame(
        [
            {"metric": "status", "value": payload["status"]},
            {"metric": "ready_a_tier_samples", "value": payload["ready_a_tier_samples"]},
            {"metric": "symbols_requested", "value": payload["symbols_requested"]},
            {"metric": "chains_imported", "value": payload["chains_imported"]},
            {"metric": "errors", "value": payload["errors"]},
        ]
    )
    (output_dir / "option_chain_import.md").write_text(
        f"""# Option Chain Import

## Summary

{markdown_table(summary)}

## Symbols

{markdown_table(rows)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload = build_import(
        output_dir=args.output_dir,
        chain_dir=args.chain_dir,
        samples_csv=args.samples_csv,
        candidate_ledger_csv=args.candidate_ledger_csv,
        account_size=args.account_size,
        max_dte=args.max_dte,
        provider=args.provider,
    )
    write_outputs(args.output_dir, payload)
    print(f"Option chain import: {payload['status']}")
    print(f"Chains imported: {payload['chains_imported']}")
    print(f"Saved {args.output_dir / 'option_chain_import.md'}")


if __name__ == "__main__":
    main()

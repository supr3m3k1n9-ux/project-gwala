"""Run the local Project Gwala app shell.

This serves a small dashboard for the research and paper workflow. It reads
`logs/system_state.json`, serves static files from `app/`, and exposes local
status-only actions that rebuild readiness reports.

It does not fetch market data, import paper trades, place orders, create
alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

from config.settings import STRATEGY
from config.investment_narratives import INVESTMENT_NARRATIVES
from config.symbol_playbook import playbook_symbols, setup_labels_for_symbol
from data.market_data import load_candles_from_csv
from indicators.session import add_opening_range, add_session_columns
from indicators.trend import add_core_indicators
from run_near_miss_analytics import build_near_miss_payload, read_observations
from run_paper_import import read_existing
from run_update_paper_trade import open_rows as open_paper_rows
from run_update_paper_trade import update_trade as update_paper_trade


PROJECT_DIR = Path(__file__).resolve().parent
APP_DIR = PROJECT_DIR / "app"
LOGS_DIR = PROJECT_DIR / "logs"
PAPER_CSV = PROJECT_DIR / "data" / "paper_trades.csv"
STATUS_ACTION_LOCK = threading.Lock()
DEFAULT_BACKTEST_STARTING_EQUITY = 5_000.0
DEFAULT_BACKTEST_RISK_PER_TRADE_PCT = 0.005
TRADING_WORKSPACE_TIMEFRAMES = {
    "M1": "M1",
    "M5": "M5",
    "M15": "M15",
    "M30": "M30",
    "M60": "M60",
    "D": "D",
}
TRADING_SIGNAL_TIMEFRAMES = {"M5", "M30"}
TRADING_WORKSPACE_SYMBOLS = playbook_symbols("approved_plus_watch")
WEBULL_PYTHON = PROJECT_DIR / ".venv-webull" / "bin" / "python"
ALLOWED_REPORTS = {
    "dashboard": "project_gwala_dashboard.md",
    "scanner": "daily_paper_signal_scanner.md",
    "observations": "forward_signal_observations.md",
    "near_misses": "near_miss_analytics.md",
    "observation_review": "forward_observation_review.md",
    "reconciliation": "observation_paper_reconciliation.md",
    "integrity": "candle_data_integrity.md",
    "refresh_audit": "market_refresh_audit.md",
    "setup_health": "setup_health.md",
    "paper_session": "paper_session_cycle.md",
    "paper_execution": "local_paper_execution_simulator.md",
    "candidate_alerts": "paper_candidate_alerts.md",
    "forward_sample_queue": "forward_sample_queue.md",
    "almost_ready_breakout": "almost_ready_breakout.md",
    "post_scan_digest": "post_scan_digest.md",
    "forward_evidence": "forward_evidence.md",
    "candidate_aging": "candidate_aging.md",
    "no_trade_analysis": "no_trade_blocker_analysis.md",
    "shadow_samples": "shadow_samples.md",
    "open_paper_monitor": "open_paper_trade_monitor.md",
    "exit_audit": "paper_exit_audit.md",
    "readiness": "readiness_check.md",
    "checkpoint": "paper_validation_checkpoint.md",
    "refresh_status": "refresh_status.md",
    "morning_watchdog": "morning_run_watchdog.md",
    "automation_timeline": "daily_automation_timeline.md",
    "premarket": "premarket_verification.md",
    "setup_replay": "setup_replay.md",
    "strategy_vault": "strategy_vault.md",
    "vwap_mean_reversion": "vwap_mean_reversion.md",
    "strategy_improvement_plan": "strategy_improvement_plan.md",
    "feature_wiring_audit": "feature_wiring_audit.md",
    "research_confidence": "universe_expansion/research_confidence.md",
    "promotion_review": "promotion_review.md",
    "controlled_variant_review": "controlled_variant_review.md",
    "walk_forward_review": "walk_forward_review.md",
    "regime_review": "regime_review.md",
    "strategy_overlap_audit": "strategy_overlap_audit.md",
    "opening_range_relaxation": "opening_range_relaxation_review.md",
    "deep_research_confidence": "deeper_research/research_confidence.md",
    "deep_promotion_review": "deeper_research/promotion_review.md",
    "deep_controlled_variant_review": "deeper_research/controlled_variant_review.md",
    "deep_walk_forward_review": "deeper_research/walk_forward_review.md",
    "deep_regime_review": "deeper_research/regime_review.md",
    "system_state": "system_state.md",
}


def workflow_python() -> str:
    """Use the Webull environment for market-data refreshes when it exists."""

    if WEBULL_PYTHON.exists():
        return str(WEBULL_PYTHON)
    return sys.executable


def app_number(value: object) -> float | None:
    """Convert chart values to clean JSON numbers."""

    if pd.isna(value):
        return None
    return round(float(value), 4)


def app_positive_float(value: object, default: float, maximum: float | None = None) -> float:
    """Read a positive app input while keeping unsafe values at a sane default."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    if maximum is not None:
        return min(number, maximum)
    return number


def add_retro_account_simulation(
    trades: pd.DataFrame,
    starting_equity: float = DEFAULT_BACKTEST_STARTING_EQUITY,
    risk_per_trade_pct: float = DEFAULT_BACKTEST_RISK_PER_TRADE_PCT,
    risk_pct_column: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Apply a simple paper-account model to historical R-multiple trades."""

    summary = {
        "starting_equity": round(starting_equity, 2),
        "ending_equity": round(starting_equity, 2),
        "total_pnl": 0.0,
        "return_pct": 0.0,
        "max_drawdown": 0.0,
        "risk_per_trade_pct": round(risk_per_trade_pct, 6),
        "average_risk_per_trade_pct": round(risk_per_trade_pct, 6),
        "max_risk_per_trade_pct": round(risk_per_trade_pct, 6),
    }
    if trades.empty or "r_result" not in trades.columns:
        return trades.copy(), summary

    simulated = trades.copy()
    if "entry_time" in simulated.columns:
        simulated = simulated.sort_values("entry_time")

    equity = starting_equity
    peak_equity = starting_equity
    max_drawdown = 0.0
    equity_before: list[float] = []
    risk_dollars: list[float] = []
    pnl_dollars: list[float] = []
    equity_after: list[float] = []
    r_results = pd.to_numeric(simulated["r_result"], errors="coerce").fillna(0.0)

    risk_pcts = (
        pd.to_numeric(simulated[risk_pct_column], errors="coerce").fillna(risk_per_trade_pct).clip(lower=0.0001, upper=0.10)
        if risk_pct_column and risk_pct_column in simulated.columns
        else pd.Series([risk_per_trade_pct] * len(simulated), index=simulated.index)
    )
    applied_risk_pct: list[float] = []

    for r_result, trade_risk_pct in zip(r_results, risk_pcts):
        trade_risk = equity * float(trade_risk_pct)
        trade_pnl = float(r_result) * trade_risk
        applied_risk_pct.append(round(float(trade_risk_pct), 6))
        equity_before.append(round(equity, 2))
        risk_dollars.append(round(trade_risk, 2))
        pnl_dollars.append(round(trade_pnl, 2))
        equity = equity + trade_pnl
        equity_after.append(round(equity, 2))
        peak_equity = max(peak_equity, equity)
        max_drawdown = min(max_drawdown, equity - peak_equity)

    simulated["account_equity_before"] = equity_before
    simulated["applied_risk_per_trade_pct"] = applied_risk_pct
    simulated["risk_dollars"] = risk_dollars
    simulated["pnl_dollars"] = pnl_dollars
    simulated["account_equity_after"] = equity_after
    timeline: dict[str, object] = {}
    if "entry_time" in simulated.columns:
        dates = pd.to_datetime(simulated["entry_time"], errors="coerce", utc=True).dropna()
        if not dates.empty:
            timeline = {
                "first_entry": dates.min().date().isoformat(),
                "last_entry": dates.max().date().isoformat(),
                "active_trade_dates": int(dates.dt.date.nunique()),
                "active_months": int(dates.dt.strftime("%Y-%m").nunique()),
            }
    summary.update(
        {
            "ending_equity": round(equity, 2),
            "total_pnl": round(equity - starting_equity, 2),
            "return_pct": round(((equity - starting_equity) / starting_equity) * 100, 2),
            "max_drawdown": round(max_drawdown, 2),
            "average_risk_per_trade_pct": round(float(pd.Series(applied_risk_pct).mean()), 6),
            "max_risk_per_trade_pct": round(float(pd.Series(applied_risk_pct).max()), 6),
            "timeline": timeline,
        }
    )
    return simulated, summary


def promotion_risk_tier(row: pd.Series, base_risk_pct: float) -> tuple[str, float, str]:
    """Assign conservative research risk tiers from objective promotion evidence."""

    score = float(row.get("readiness_score", 0) or 0)
    expectancy = float(row.get("expectancy_r", 0) or 0)
    win_rate = float(row.get("win_rate_pct", 0) or 0)
    drawdown = float(row.get("max_drawdown_r", 0) or 0)

    if score >= 80 and expectancy >= 0.18 and win_rate >= 58 and drawdown >= -2.25:
        return "best_tier", min(base_risk_pct * 2.0, 0.02), "Score 80+, expectancy 0.18R+, win rate 58%+, drawdown no worse than -2.25R."
    if score >= 70 and expectancy >= 0.14 and win_rate >= 52 and drawdown >= -2.75:
        return "strong", min(base_risk_pct * 1.5, 0.015), "Score 70+, expectancy 0.14R+, win rate 52%+, drawdown no worse than -2.75R."
    return "standard", base_risk_pct, "Standard promoted setup risk."


def build_backtest_portfolio_simulation(
    logs_dir: Path,
    starting_equity: float = DEFAULT_BACKTEST_STARTING_EQUITY,
    risk_per_trade_pct: float = DEFAULT_BACKTEST_RISK_PER_TRADE_PCT,
    risk_model: str = "fixed",
) -> tuple[pd.DataFrame, dict]:
    """Build a deduped research-account simulation from promoted backtest rows."""

    promotion_path = logs_dir / "promotion_review.csv"
    if not promotion_path.exists():
        raise FileNotFoundError("logs/promotion_review.csv was not found. Run promotion review first.")

    promotion = pd.read_csv(promotion_path)
    if promotion.empty or "trade_log" not in promotion.columns:
        empty, account = add_retro_account_simulation(pd.DataFrame(), starting_equity, risk_per_trade_pct)
        account.update({"source_candidates": 0, "source_files": 0, "duplicates_collapsed": 0})
        return empty, account

    if "promotion_decision" in promotion.columns:
        selected = promotion[promotion["promotion_decision"].eq("paper_watch_candidate")].copy()
    else:
        selected = promotion.copy()
    if selected.empty:
        empty, account = add_retro_account_simulation(pd.DataFrame(), starting_equity, risk_per_trade_pct)
        account.update({"source_candidates": 0, "source_files": 0, "duplicates_collapsed": 0})
        return empty, account

    frames: list[pd.DataFrame] = []
    source_files = 0
    for _, row in selected.iterrows():
        trade_log = str(row.get("trade_log", "")).strip()
        if not trade_log:
            continue
        trade_path = PROJECT_DIR / trade_log
        if not (trade_path.exists() and logs_dir in trade_path.parents):
            trade_path = logs_dir / Path(trade_log).name
        if not trade_path.exists():
            continue
        try:
            trades = pd.read_csv(trade_path)
        except pd.errors.EmptyDataError:
            continue
        if trades.empty or "r_result" not in trades.columns:
            continue
        trades = trades.copy()
        trades["source_candidate"] = row.get("candidate", "")
        trades["source_setup"] = row.get("setup", "")
        trades["source_trade_log"] = trade_path.name
        tier, tier_risk_pct, tier_reason = promotion_risk_tier(row, risk_per_trade_pct)
        trades["research_risk_tier"] = tier if risk_model == "tiered" else "fixed"
        trades["research_risk_reason"] = tier_reason if risk_model == "tiered" else "Fixed risk model selected."
        trades["research_risk_pct"] = tier_risk_pct if risk_model == "tiered" else risk_per_trade_pct
        frames.append(trades)
        source_files += 1

    if not frames:
        empty, account = add_retro_account_simulation(pd.DataFrame(), starting_equity, risk_per_trade_pct)
        account.update({"source_candidates": int(len(selected)), "source_files": 0, "duplicates_collapsed": 0})
        return empty, account

    combined = pd.concat(frames, ignore_index=True)
    before_dedupe = len(combined)
    dedupe_columns = [
        column
        for column in ["symbol", "entry_time", "exit_time", "setup_type", "entry", "stop", "target", "r_result"]
        if column in combined.columns
    ]
    if dedupe_columns:
        combined = combined.drop_duplicates(subset=dedupe_columns, keep="first")
    combined, account = add_retro_account_simulation(
        combined,
        starting_equity,
        risk_per_trade_pct,
        risk_pct_column="research_risk_pct" if risk_model == "tiered" else None,
    )
    account.update(
        {
            "source_candidates": int(len(selected)),
            "source_files": int(source_files),
            "duplicates_collapsed": int(before_dedupe - len(combined)),
            "risk_model": risk_model,
        }
    )
    return combined, account


def approved_setup_labels(symbol: str) -> list[str]:
    """Return the approved setup directions shown beside a chart symbol."""

    return setup_labels_for_symbol(symbol, "approved_plus_watch")


def build_trading_workspace_data(
    logs_dir: Path,
    symbol: str = "SPY",
    timeframe: str = "M5",
) -> dict:
    """Build a read-only chart snapshot from locally saved Webull candles."""

    symbol = symbol.upper()
    timeframe = timeframe.upper()
    if symbol not in TRADING_WORKSPACE_SYMBOLS:
        raise ValueError(f"{symbol} is not in the approved/watch paper-validation universe.")
    if timeframe not in TRADING_WORKSPACE_TIMEFRAMES:
        supported = ", ".join(TRADING_WORKSPACE_TIMEFRAMES)
        raise ValueError(f"Supported chart timeframes are {supported}.")

    candle_path = logs_dir / f"webull_{symbol}_{TRADING_WORKSPACE_TIMEFRAMES[timeframe]}_candles.csv"
    opening_range_path = logs_dir / f"webull_{symbol}_M5_candles.csv"
    if not candle_path.exists() or not opening_range_path.exists():
        raise FileNotFoundError(f"Saved Webull candles are missing for {symbol}.")

    candles = load_candles_from_csv(candle_path, symbol)
    lower_candles = load_candles_from_csv(opening_range_path, symbol)
    candles = add_core_indicators(
        candles,
        fast_length=STRATEGY.fast_ema_length,
        slow_length=STRATEGY.slow_ema_length,
        regime_length=STRATEGY.regime_ema_length,
    )
    candles = add_session_columns(candles, STRATEGY)
    candles = add_opening_range(candles, lower_candles, STRATEGY)
    if timeframe != "D":
        candles = candles[candles["regular_session"]].copy()
    if candles.empty:
        raise ValueError(f"No chart candles are available for {symbol}.")

    latest_session = candles["session_date"].iloc[-1]
    display_limits = {"M1": 120, "M5": 90, "M15": 96, "M30": 80, "M60": 90, "D": 130}
    display_limit = display_limits.get(timeframe, 80)
    if timeframe in {"M1", "M5", "M15"}:
        display = candles[candles["session_date"] == latest_session].tail(display_limit)
    else:
        display = candles.tail(display_limit)
    latest = candles.iloc[-1]
    earlier_sessions = candles[candles["session_date"] < latest_session]
    if not earlier_sessions.empty:
        reference_close = earlier_sessions.iloc[-1]["close"]
    elif len(candles) > 1:
        reference_close = candles.iloc[-2]["close"]
    else:
        reference_close = latest["close"]
    change = float(latest["close"]) - float(reference_close)
    change_pct = change / float(reference_close) * 100 if float(reference_close) else 0.0

    rows = []
    for timestamp, row in display.iterrows():
        rows.append(
            {
                "time_et": timestamp.tz_convert(STRATEGY.market_timezone).strftime("%m/%d %H:%M"),
                "session_date": str(row["session_date"]),
                "open": app_number(row["open"]),
                "high": app_number(row["high"]),
                "low": app_number(row["low"]),
                "close": app_number(row["close"]),
                "volume": int(row["volume"]),
                "vwap": app_number(row["vwap"]),
                "ema_9": app_number(row[f"ema_{STRATEGY.fast_ema_length}"]),
                "ema_21": app_number(row[f"ema_{STRATEGY.slow_ema_length}"]),
                "ema_200": app_number(row[f"ema_{STRATEGY.regime_ema_length}"]),
                "opening_range_high": app_number(row["opening_range_high"]),
                "opening_range_low": app_number(row["opening_range_low"]),
            }
        )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": f"Saved Webull {timeframe} market-data candles",
        "timeframe_role": "strategy signal timeframe" if timeframe in TRADING_SIGNAL_TIMEFRAMES else "chart-only review timeframe",
        "latest_session": str(latest_session),
        "latest_bar_et": latest["local_time"].strftime("%Y-%m-%d %H:%M %Z"),
        "latest_bar_iso": latest["local_time"].isoformat(),
        "data_lag_minutes": max(
            round((pd.Timestamp.now(tz=STRATEGY.market_timezone) - latest["local_time"]).total_seconds() / 60, 1),
            0,
        ),
        "last_price": app_number(latest["close"]),
        "day_change": round(change, 4),
        "day_change_pct": round(change_pct, 2),
        "approved_setups": approved_setup_labels(symbol),
        "available_symbols": [
            {
                "symbol": allowed_symbol,
                "setups": approved_setup_labels(allowed_symbol),
            }
            for allowed_symbol in TRADING_WORKSPACE_SYMBOLS
        ],
        "available_timeframes": [
            {
                "timeframe": label,
                "label": "1h" if label == "M60" else "Daily" if label == "D" else label.replace("M", "") + "m",
                "exists": (logs_dir / f"webull_{symbol}_{saved}_candles.csv").exists(),
                "role": "signal" if label in TRADING_SIGNAL_TIMEFRAMES else "chart_only",
            }
            for label, saved in TRADING_WORKSPACE_TIMEFRAMES.items()
        ],
        "candles": rows,
    }


def build_replay_chart_data(
    logs_dir: Path,
    replay_id: int,
    revealed: bool = False,
    step: int | None = None,
) -> dict:
    """Build a concealed or revealed historical chart for one replay card.

    Before reveal, the payload ends at the entry bar so later price action is
    not shown during the practice decision. During step-by-step management,
    only the requested number of saved management bars is returned. After
    reveal, saved 5-minute bars are preferred because that is the
    exit-management timeframe.
    """

    replay_path = logs_dir / "setup_replay.json"
    if not replay_path.exists():
        raise FileNotFoundError("Saved setup replay cards are missing.")

    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    cards = replay.get("cards", [])
    card = next((item for item in cards if int(item.get("replay_id", -1)) == replay_id), None)
    if card is None:
        raise ValueError(f"Replay {replay_id} is not available.")

    symbol = str(card["symbol"]).upper()
    entry_time = pd.to_datetime(card["entry_time"], utc=True)
    exit_time = pd.to_datetime(card["exit_time"], utc=True)
    session_date = entry_time.tz_convert(STRATEGY.market_timezone).date()

    def load_timeframe(timeframe: str) -> pd.DataFrame:
        candle_path = logs_dir / f"webull_{symbol}_{timeframe}_candles.csv"
        opening_range_path = logs_dir / f"webull_{symbol}_M5_candles.csv"
        if not candle_path.exists() or not opening_range_path.exists():
            raise FileNotFoundError(f"Saved Webull candles are missing for {symbol}.")

        candles = load_candles_from_csv(candle_path, symbol)
        lower_candles = load_candles_from_csv(opening_range_path, symbol)
        candles = add_core_indicators(
            candles,
            fast_length=STRATEGY.fast_ema_length,
            slow_length=STRATEGY.slow_ema_length,
            regime_length=STRATEGY.regime_ema_length,
        )
        candles = add_session_columns(candles, STRATEGY)
        candles = add_opening_range(candles, lower_candles, STRATEGY)
        return candles[candles["regular_session"]].copy()

    if step is not None and step < 0:
        raise ValueError("Replay candle step must be zero or greater.")

    management_active = step is not None
    timeframe = "M30"
    candles = load_timeframe(timeframe)
    if revealed or management_active:
        exit_candles = load_timeframe("M5")
        session_exit_candles = exit_candles[exit_candles["session_date"] == session_date]
        if not session_exit_candles.empty and session_exit_candles.index.min() <= entry_time:
            timeframe = "M5"
            candles = exit_candles

    session_candles = candles[candles["session_date"] == session_date].copy()
    management_candles = session_candles[(session_candles.index > entry_time) & (session_candles.index <= exit_time)]
    available_steps = int(len(management_candles))
    visible_step = min(step or 0, available_steps)
    if revealed:
        cutoff = exit_time
    elif management_active and visible_step:
        cutoff = management_candles.index[visible_step - 1]
    else:
        cutoff = entry_time
    display = candles[(candles["session_date"] == session_date) & (candles.index <= cutoff)].copy()
    if display.empty:
        raise ValueError(f"No saved chart bars are available for replay {replay_id}.")

    rows = []
    for timestamp, row in display.iterrows():
        rows.append(
            {
                "time_et": timestamp.tz_convert(STRATEGY.market_timezone).strftime("%m/%d %H:%M"),
                "session_date": str(row["session_date"]),
                "open": app_number(row["open"]),
                "high": app_number(row["high"]),
                "low": app_number(row["low"]),
                "close": app_number(row["close"]),
                "volume": int(row["volume"]),
                "vwap": app_number(row["vwap"]),
                "ema_9": app_number(row[f"ema_{STRATEGY.fast_ema_length}"]),
                "ema_21": app_number(row[f"ema_{STRATEGY.slow_ema_length}"]),
                "ema_200": app_number(row[f"ema_{STRATEGY.regime_ema_length}"]),
                "opening_range_high": app_number(row["opening_range_high"]),
                "opening_range_low": app_number(row["opening_range_low"]),
            }
        )

    def marker(event_time: pd.Timestamp, label: str, kind: str) -> dict:
        eligible = display[display.index <= event_time]
        timestamp = eligible.index[-1] if not eligible.empty else display.index[0]
        return {
            "time_et": timestamp.tz_convert(STRATEGY.market_timezone).strftime("%m/%d %H:%M"),
            "label": label,
            "kind": kind,
        }

    markers = [marker(entry_time, "E", "entry")]
    if revealed:
        markers.append(marker(exit_time, "X", "exit"))

    current_r = None
    current_price = None
    if management_active and visible_step:
        current_price = float(display.iloc[-1]["close"])
        entry_price = float(card["entry"])
        risk = abs(entry_price - float(card["stop"]))
        if risk:
            direction_multiplier = 1 if str(card.get("direction", "")).lower() == "long" else -1
            current_r = round(((current_price - entry_price) / risk) * direction_multiplier, 4)

    return {
        "replay_id": replay_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "outcome_revealed": revealed,
        "management_active": management_active,
        "step": visible_step if management_active else None,
        "available_steps": available_steps if revealed or (management_active and visible_step >= available_steps) else None,
        "management_complete": management_active and visible_step >= available_steps,
        "current_price": app_number(current_price) if current_price is not None else None,
        "current_r": current_r,
        "source": f"Saved Webull {timeframe} historical candles",
        "chart_note": (
            f"Outcome shown through exit on the {timeframe} chart."
            if revealed
            else (
                (
                    f"No additional stored {timeframe} management bars are available; comparison is ready."
                    if not available_steps
                    else "Final stored management candle reached. Historical outcome remains hidden."
                    if visible_step >= available_steps
                    else f"Management candle {visible_step} is visible. Historical outcome remains hidden."
                    if visible_step
                    else f"Management view ready on {timeframe}. Advance one candle at a time."
                )
                if management_active
                else "Decision view ends at the entry bar. Future historical bars remain hidden."
            )
        ),
        "candles": rows,
        "markers": markers,
        "plan_levels": [
            {"label": "Entry", "value": app_number(card["entry"]), "kind": "entry"},
            {"label": "Stop", "value": app_number(card["stop"]), "kind": "stop"},
            {"label": "Target", "value": app_number(card["target"]), "kind": "target"},
        ],
    }


def build_investment_narrative_data(symbol: str = "SPY") -> dict:
    """Return long-term research prompts without creating trade signals."""

    symbol = symbol.upper()
    if symbol not in TRADING_WORKSPACE_SYMBOLS:
        raise ValueError(f"{symbol} is not in the approved paper-validation universe.")

    narrative = INVESTMENT_NARRATIVES.get(symbol, {})
    return {
        "symbol": symbol,
        "asset_type": narrative.get("asset_type", "Approved research symbol"),
        "scope": "Long-term context only",
        "source_status": "sources_not_connected",
        "source_status_label": "Sources Not Connected",
        "summary": (
            "No live headline or X source is connected yet. Once an approved source is configured, "
            "this area can summarize sourced developments and trend themes for long-term review."
        ),
        "thesis_focus": narrative.get(
            "thesis_focus",
            "Monitor durable business or market developments before forming a long-term investment thesis.",
        ),
        "monitoring_themes": narrative.get("monitoring_themes", []),
        "review_questions": narrative.get("review_questions", []),
        "source_slots": [
            {
                "label": "Market news and company reports",
                "status": "Not connected",
                "detail": "Connect a licensed or approved news source before generating summaries.",
            },
            {
                "label": "X public-post trends",
                "status": "Not connected",
                "detail": "Use the official X API with refresh and spending limits when enabled.",
            },
        ],
        "guardrail": (
            "Narrative context is excluded from strategy scoring, entries, exits, "
            "position sizing, and paper-trade eligibility."
        ),
    }


def split_scanner_conditions(value: object) -> list[str]:
    """Convert scanner condition text into dashboard checklist entries."""

    if value is None or pd.isna(value):
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def build_setup_readiness_data(logs_dir: Path, symbol: str = "SPY") -> dict:
    """Return read-only setup explanations and signal markers from scanner output."""

    symbol = symbol.upper()
    if symbol not in TRADING_WORKSPACE_SYMBOLS:
        raise ValueError(f"{symbol} is not in the approved paper-validation universe.")

    scanner_path = logs_dir / "daily_paper_signal_scanner.csv"
    if not scanner_path.exists():
        return {
            "symbol": symbol,
            "status": "missing_scanner",
            "setups": [],
            "signal_markers": [],
            "message": "Run the local daily scanner to populate setup readiness.",
            "guardrail": "Readiness explanations do not create or approve paper trades.",
        }

    scanner = pd.read_csv(scanner_path)
    selected = scanner[scanner["symbol"].astype(str).str.upper() == symbol]
    setups = []
    markers = []
    for _, row in selected.iterrows():
        scanner_status = str(row.get("scanner_status", "not_ready"))
        signal_freshness = "" if pd.isna(row.get("signal_freshness")) else str(row.get("signal_freshness", ""))
        signal_time = "" if pd.isna(row.get("latest_signal_et")) else str(row.get("latest_signal_et", ""))
        if scanner_status == "allowed" and signal_freshness == "current_candle":
            status_label = "Current Signal"
            status_tone = "healthy"
        elif scanner_status == "blocked_watch_only" and signal_freshness == "current_candle":
            status_label = "Watch Only"
            status_tone = "watch"
        elif scanner_status == "allowed" and signal_freshness == "earlier_today":
            status_label = "Triggered Earlier"
            status_tone = "review_only"
        elif scanner_status == "blocked_watch_only" and signal_freshness == "earlier_today":
            status_label = "Watch Signal Earlier"
            status_tone = "watch"
        elif scanner_status == "data_error":
            status_label = "Data Error"
            status_tone = "caution"
        else:
            status_label = "Not Ready"
            status_tone = "watch"

        missing = split_scanner_conditions(row.get("missing_conditions"))
        passed = split_scanner_conditions(row.get("passed_conditions"))
        if not missing and "latest candle gaps:" in str(row.get("latest_candle_notes", "")):
            missing = split_scanner_conditions(str(row["latest_candle_notes"]).split("latest candle gaps:", 1)[1])
        elif not missing and scanner_status == "not_ready":
            missing = split_scanner_conditions(row.get("latest_candle_notes"))

        setups.append(
            {
                "setup": str(row["setup"]),
                "direction": str(row["direction"]),
                "status_label": status_label,
                "status_tone": status_tone,
                "latest_candle_et": str(row.get("latest_candle_et", "")),
                "latest_signal_et": signal_time,
                "signal_freshness": signal_freshness,
                "quality_grade": "" if pd.isna(row.get("quality_grade")) else str(row.get("quality_grade", "")),
                "quality_score": app_number(row.get("quality_score")),
                "relative_volume": app_number(row.get("relative_volume")),
                "room_to_target_r": app_number(row.get("room_to_target_r")),
                "passed_conditions": passed,
                "missing_conditions": missing,
                "condition_count": int(row.get("condition_count", len(passed) + len(missing)) or 0),
                "passed_condition_count": int(row.get("passed_condition_count", len(passed)) or 0),
                "notes": str(row.get("notes", "")),
            }
        )
        if signal_time:
            markers.append(
                {
                    "time_et": pd.to_datetime(signal_time).strftime("%m/%d %H:%M"),
                    "setup": str(row["setup"]),
                    "label": "A" if "Setup A" in str(row["setup"]) else "B",
                    "direction": str(row["direction"]),
                    "scanner_status": scanner_status,
                    "signal_freshness": signal_freshness,
                }
            )

    return {
        "symbol": symbol,
        "status": "available",
        "setups": setups,
        "signal_markers": markers,
        "message": "Conditions reflect the latest saved scanner candle. Markers show scanner signals found in the stored session.",
        "guardrail": "Readiness explanations do not create signals, approve paper trades, or alter position sizing.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Project Gwala app shell.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to serve.")
    return parser.parse_args()


class ProjectGwalaHandler(SimpleHTTPRequestHandler):
    """Serve static app files and tightly scoped local JSON actions."""

    def end_headers(self) -> None:
        """Keep the local dashboard from reusing stale app assets."""

        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/system-state":
            self.serve_system_state()
            return
        if parsed.path == "/api/trading-workspace":
            self.serve_trading_workspace(parsed.query)
            return
        if parsed.path == "/api/investment-narrative":
            self.serve_investment_narrative(parsed.query)
            return
        if parsed.path == "/api/setup-readiness":
            self.serve_setup_readiness(parsed.query)
            return
        if parsed.path == "/api/replay-chart":
            self.serve_replay_chart(parsed.query)
            return
        if parsed.path == "/api/near-miss-analytics":
            self.serve_near_miss_analytics()
            return
        if parsed.path == "/api/backtest-trades":
            self.serve_backtest_trades(parsed.query)
            return
        if parsed.path == "/api/backtest-portfolio":
            self.serve_backtest_portfolio(parsed.query)
            return
        if parsed.path == "/api/open-paper-trades":
            self.serve_open_paper_trades()
            return
        if parsed.path == "/api/report":
            self.serve_report(parsed.query)
            return
        if parsed.path.startswith("/logs/"):
            self.serve_log_file()
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/actions/refresh-status":
            self.run_refresh_status_action()
            return
        if parsed.path == "/api/actions/refresh-webull-data":
            self.run_refresh_webull_data_action()
            return
        if parsed.path == "/api/actions/premarket-check":
            self.run_premarket_check_action()
            return
        if parsed.path == "/api/actions/paper-session-preview":
            self.run_paper_session_action("preview")
            return
        if parsed.path == "/api/actions/paper-session-confirm-entry":
            self.run_paper_session_action("confirm_entry")
            return
        if parsed.path == "/api/actions/paper-session-confirm-exits":
            self.run_paper_session_action("confirm_exits")
            return
        if parsed.path == "/api/actions/update-paper-trade":
            self.run_update_paper_trade_action()
            return
        self.send_error(404, "Action is not allowed.")

    def send_json(self, payload: dict, status: int = 200) -> None:
        """Write a JSON API response without browser caching."""

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        """Read a small JSON POST body."""

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        data = json.loads(body)
        return data if isinstance(data, dict) else {}

    def serve_system_state(self) -> None:
        """Return the current app-ready system state JSON."""

        path = LOGS_DIR / "system_state.json"
        if not path.exists():
            self.send_error(404, "logs/system_state.json not found. Run python run_system_state.py first.")
            return

        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.send_error(500, "logs/system_state.json is invalid. Run python run_system_state.py again.")
            return
        self.send_json(state)

    def serve_trading_workspace(self, query: str) -> None:
        """Return read-only chart data derived from locally saved Webull bars."""

        params = parse_qs(query)
        symbol = params.get("symbol", ["SPY"])[0]
        timeframe = params.get("timeframe", ["M5"])[0]
        try:
            payload = build_trading_workspace_data(LOGS_DIR, symbol, timeframe)
        except (FileNotFoundError, ValueError) as error:
            self.send_json({"error": str(error)}, status=404)
            return
        self.send_json(payload)

    def serve_investment_narrative(self, query: str) -> None:
        """Return non-signal long-term research context for an approved symbol."""

        params = parse_qs(query)
        symbol = params.get("symbol", ["SPY"])[0]
        try:
            payload = build_investment_narrative_data(symbol)
        except ValueError as error:
            self.send_json({"error": str(error)}, status=404)
            return
        self.send_json(payload)

    def serve_setup_readiness(self, query: str) -> None:
        """Return setup conditions and in-session signal markers for the chart."""

        params = parse_qs(query)
        symbol = params.get("symbol", ["SPY"])[0]
        try:
            payload = build_setup_readiness_data(LOGS_DIR, symbol)
        except ValueError as error:
            self.send_json({"error": str(error)}, status=404)
            return
        self.send_json(payload)

    def serve_replay_chart(self, query: str) -> None:
        """Return saved historical chart bars for process-only replay practice."""

        params = parse_qs(query)
        try:
            replay_id = int(params.get("id", [""])[0])
            revealed = params.get("revealed", ["false"])[0].lower() == "true"
            step = int(params["step"][0]) if "step" in params else None
            payload = build_replay_chart_data(LOGS_DIR, replay_id, revealed, step)
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError) as error:
            self.send_json({"error": str(error)}, status=404)
            return
        self.send_json(payload)

    def serve_near_miss_analytics(self) -> None:
        """Return blocker patterns without changing scanner or paper state."""

        scanner_path = LOGS_DIR / "daily_paper_signal_scanner.csv"
        if not scanner_path.exists():
            self.send_json({"error": "Run the local daily scanner to populate near-miss analytics."}, status=404)
            return
        scanner = pd.read_csv(scanner_path)
        observations = read_observations(PROJECT_DIR / "data" / "near_miss_observations.csv")
        results_path = LOGS_DIR / "forward_observation_results.csv"
        results = pd.read_csv(results_path) if results_path.exists() else pd.DataFrame()
        self.send_json(build_near_miss_payload(scanner, observations, results))

    def serve_report(self, query: str) -> None:
        """Return an allowed Markdown report as JSON for the app."""

        params = parse_qs(query)
        report_key = params.get("name", [""])[0]
        filename = ALLOWED_REPORTS.get(report_key)
        if filename is None:
            self.send_error(404, "Report is not allowed.")
            return

        path = LOGS_DIR / filename
        if not path.exists():
            self.send_error(404, f"{filename} not found.")
            return

        payload = {
            "name": report_key,
            "filename": filename,
            "content": path.read_text(encoding="utf-8"),
        }
        self.send_json(payload)

    def serve_backtest_trades(self, query: str) -> None:
        """Return a safe simulated backtest trade CSV for dashboard review."""

        params = parse_qs(query)
        raw_name = params.get("file", [""])[0]
        starting_equity = app_positive_float(
            params.get("starting_equity", [DEFAULT_BACKTEST_STARTING_EQUITY])[0],
            DEFAULT_BACKTEST_STARTING_EQUITY,
            maximum=1_000_000.0,
        )
        risk_per_trade_pct = app_positive_float(
            params.get("risk_per_trade_pct", [DEFAULT_BACKTEST_RISK_PER_TRADE_PCT])[0],
            DEFAULT_BACKTEST_RISK_PER_TRADE_PCT,
            maximum=0.10,
        )
        safe_name = Path(raw_name).name
        if not safe_name.endswith(("_baseline_trades.csv", "_elite_trades.csv")):
            self.send_json({"error": "Backtest trade file is not allowed."}, status=404)
            return

        path = LOGS_DIR / safe_name
        if not path.exists():
            self.send_json({"error": f"{safe_name} was not found."}, status=404)
            return

        try:
            trades = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            trades = pd.DataFrame()

        trades, account = add_retro_account_simulation(trades, starting_equity, risk_per_trade_pct)
        columns = [
            "symbol",
            "entry_time",
            "exit_time",
            "quality_grade",
            "quality_score",
            "entry",
            "stop",
            "target",
            "exit_price",
            "r_result",
            "risk_dollars",
            "pnl_dollars",
            "account_equity_after",
            "exit_reason",
            "relative_volume",
            "room_to_resistance_r",
        ]
        available = [column for column in columns if column in trades.columns]
        payload = {
            "filename": safe_name,
            "row_count": int(len(trades)),
            "account": account,
            "columns": available,
            "rows": trades[available].head(200).fillna("").to_dict("records") if available else [],
        }
        self.send_json(payload)

    def serve_backtest_portfolio(self, query: str) -> None:
        """Return a deduped promoted-backtest research account simulation."""

        params = parse_qs(query)
        starting_equity = app_positive_float(
            params.get("starting_equity", [DEFAULT_BACKTEST_STARTING_EQUITY])[0],
            DEFAULT_BACKTEST_STARTING_EQUITY,
            maximum=1_000_000.0,
        )
        risk_per_trade_pct = app_positive_float(
            params.get("risk_per_trade_pct", [DEFAULT_BACKTEST_RISK_PER_TRADE_PCT])[0],
            DEFAULT_BACKTEST_RISK_PER_TRADE_PCT,
            maximum=0.10,
        )
        risk_model = params.get("risk_model", ["fixed"])[0]
        if risk_model not in {"fixed", "tiered"}:
            risk_model = "fixed"
        try:
            trades, account = build_backtest_portfolio_simulation(
                LOGS_DIR,
                starting_equity,
                risk_per_trade_pct,
                risk_model=risk_model,
            )
        except FileNotFoundError as error:
            self.send_json({"error": str(error)}, status=404)
            return

        columns = [
            "symbol",
            "entry_time",
            "exit_time",
            "source_setup",
            "source_candidate",
            "quality_grade",
            "quality_score",
            "entry",
            "stop",
            "target",
            "exit_price",
            "r_result",
            "research_risk_tier",
            "applied_risk_per_trade_pct",
            "risk_dollars",
            "pnl_dollars",
            "account_equity_after",
            "exit_reason",
            "relative_volume",
            "research_risk_reason",
            "source_trade_log",
        ]
        available = [column for column in columns if column in trades.columns]
        payload = {
            "row_count": int(len(trades)),
            "account": account,
            "columns": available,
            "rows": trades[available].head(500).fillna("").to_dict("records") if available else [],
            "guardrail": "Promoted historical backtest simulation only. This is not the live paper log or broker execution.",
        }
        self.send_json(payload)

    def serve_open_paper_trades(self) -> None:
        """Return paper-trade rows that still need outcome logging."""

        trades = read_existing(PAPER_CSV)
        rows = open_paper_rows(trades)
        self.send_json(
            {
                "row_count": int(len(rows)),
                "rows": rows.fillna("").to_dict("records"),
                "guardrail": "Local paper log only. This endpoint does not place broker orders.",
            }
        )

    def run_update_paper_trade_action(self) -> None:
        """Update one local paper row from the dashboard logger."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A paper-log update is already running."}, status=409)
            return

        try:
            payload = self.read_json_body()
            args = argparse.Namespace(
                row=int(payload.get("row", 0)),
                actual_entry=float(payload["actual_entry"]),
                actual_exit=float(payload["actual_exit"]),
                exit_time=str(payload.get("exit_time", "")).strip() or None,
                shares=int(payload["shares"]) if str(payload.get("shares", "")).strip() else None,
                vehicle=str(payload.get("vehicle", "")).strip() or None,
                risk_tier=str(payload.get("risk_tier", "")).strip() or None,
                planned_option_premium=(
                    float(payload["planned_option_premium"])
                    if str(payload.get("planned_option_premium", "")).strip()
                    else None
                ),
                followed_plan=str(payload.get("followed_plan", "")).strip() or None,
                exit_reason=str(payload.get("exit_reason", "")).strip() or None,
                notes=str(payload.get("notes", "")).strip() or None,
                append_notes=bool(payload.get("append_notes", True)),
            )
            trades = read_existing(PAPER_CSV)
            updated = update_paper_trade(trades, args)
            PAPER_CSV.parent.mkdir(parents=True, exist_ok=True)
            updated.to_csv(PAPER_CSV, index=False)

            for command in [
                [sys.executable, "run_paper_review.py"],
                [sys.executable, "run_refresh_status.py"],
                [sys.executable, "run_system_state.py"],
            ]:
                subprocess.run(
                    command,
                    cwd=PROJECT_DIR,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            row = updated.iloc[args.row - 1]
            self.send_json(
                {
                    "action": "update_paper_trade",
                    "message": (
                        f"Updated local paper row {args.row}: {row['symbol']} {row['setup']} "
                        f"outcome_r={row['outcome_r']}. No broker orders were placed."
                    ),
                    "state": state,
                }
            )
        except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError) as error:
            self.send_json({"error": f"Paper-log update rejected: {error}"}, status=400)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Paper-log update failed: {error}")
            self.send_json(
                {"error": "Paper-log update failed after writing. Review data/paper_trades.csv and logs."},
                status=500,
            )
        finally:
            STATUS_ACTION_LOCK.release()

    def run_refresh_status_action(self) -> None:
        """Rebuild readiness reports only; this never fetches market data."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A refresh-status update is already running."}, status=409)
            return

        try:
            commands = [
                [sys.executable, "run_refresh_status.py"],
                [sys.executable, "run_system_state.py"],
            ]
            for command in commands:
                subprocess.run(
                    command,
                    cwd=PROJECT_DIR,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            self.send_json(
                {
                    "action": "refresh_status",
                    "message": "Refresh status updated. No market data was fetched and no paper trades were imported.",
                    "state": state,
                }
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Refresh-status action failed: {error}")
            self.send_json(
                {"error": "Refresh-status update failed. Run python run_refresh_status.py in the terminal."},
                status=500,
            )
        finally:
            STATUS_ACTION_LOCK.release()

    def run_refresh_webull_data_action(self) -> None:
        """Refresh Webull market-data CSVs and rebuild reports; never trade."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A Webull data refresh is already running."}, status=409)
            return

        try:
            subprocess.run(
                [workflow_python(), "run_daily_workflow.py", "--refresh-data"],
                cwd=PROJECT_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=900,
            )
            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            self.send_json(
                {
                    "action": "refresh_webull_data",
                    "message": (
                        "Webull market-data refresh completed. Reports were rebuilt, paper import stayed manual, "
                        "and no broker orders or real trades were placed."
                    ),
                    "state": state,
                }
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Webull data refresh action failed: {error}")
            self.send_json(
                {"error": "Webull data refresh failed. Review terminal output or logs, then retry."},
                status=500,
            )
        finally:
            STATUS_ACTION_LOCK.release()

    def run_premarket_check_action(self) -> None:
        """Run local pre-market checks only; never request Webull data."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A readiness update is already running."}, status=409)
            return

        try:
            subprocess.run(
                [sys.executable, "run_premarket_verification.py"],
                cwd=PROJECT_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            self.send_json(
                {
                    "action": "premarket_check",
                    "message": "Local pre-market verification updated. No market data was fetched and no paper trades were imported.",
                    "state": state,
                }
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Pre-market check action failed: {error}")
            self.send_json(
                {"error": "Pre-market verification failed. Review logs/premarket_verification.md."},
                status=500,
            )
        finally:
            STATUS_ACTION_LOCK.release()

    def run_paper_session_action(self, mode: str) -> None:
        """Run the local paper session cycle with an explicitly allowed mode."""

        allowed_modes = {
            "preview": {
                "flags": [],
                "message": "Paper session preview updated. No local paper entries or exits were written.",
            },
            "confirm_entry": {
                "flags": ["--confirm-local-paper"],
                "message": "Local paper entry cycle completed. This wrote local paper rows only if eligible rows were present.",
            },
            "confirm_exits": {
                "flags": ["--confirm-exits"],
                "message": "Local paper exit cycle completed. This wrote local paper exits only if completed exits were present.",
            },
        }
        selected = allowed_modes.get(mode)
        if selected is None:
            self.send_json({"error": "Paper session mode is not allowed."}, status=404)
            return

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A paper session cycle is already running."}, status=409)
            return

        try:
            subprocess.run(
                [sys.executable, "run_paper_session_cycle.py", *selected["flags"]],
                cwd=PROJECT_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=240,
            )
            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            self.send_json(
                {
                    "action": f"paper_session_{mode}",
                    "message": f"{selected['message']} No broker orders, Webull paper orders, or real trades were placed.",
                    "state": state,
                }
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Paper session action failed: {error}")
            self.send_json(
                {"error": "Paper session cycle failed. Review logs/paper_session_cycle.md or run it in the terminal."},
                status=500,
            )
        finally:
            STATUS_ACTION_LOCK.release()

    def serve_log_file(self) -> None:
        """Serve selected read-only log files used by the dashboard links."""

        raw_name = unquote(urlparse(self.path).path.removeprefix("/logs/"))
        safe_name = Path(raw_name).name
        path = LOGS_DIR / safe_name
        if not path.exists() or path.suffix not in {".md", ".csv", ".json"}:
            self.send_error(404, "Log file not found.")
            return

        content_type = {
            ".md": "text/markdown; charset=utf-8",
            ".csv": "text/csv; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }[path.suffix]

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def log_message(self, format: str, *args) -> None:
        """Keep server output compact."""

        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    args = parse_args()
    if not APP_DIR.exists():
        raise FileNotFoundError("app/ folder is missing.")

    handler = lambda *handler_args, **handler_kwargs: ProjectGwalaHandler(
        *handler_args,
        directory=str(APP_DIR),
        **handler_kwargs,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Project Gwala app: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProject Gwala app stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

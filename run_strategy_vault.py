"""Build the live-facing strategy vault report.

This report answers a simple question: which strategy family deserves attention
under the current market backdrop? It is a router for research and manual paper
review only. It never creates trades, imports paper entries, places broker
orders, or changes scanner rules.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import STRATEGY
from config.strategy_vault import STRATEGY_VAULT, VaultStrategy
from data.market_data import load_candles_from_csv
from indicators.trend import add_core_indicators
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Project Gwala strategy vault report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--market-symbol", default="SPY", help="Market symbol used as the broad regime proxy.")
    parser.add_argument("--timeframe", default="M30", help="Saved Webull candle timeframe used for regime detection.")
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if it exists and can be parsed."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read JSON data if available."""

    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def true_range_percent(candles: pd.DataFrame) -> pd.Series:
    """Return true range as a percent of close."""

    previous_close = candles["close"].shift(1)
    true_range = pd.concat(
        [
            candles["high"] - candles["low"],
            (candles["high"] - previous_close).abs(),
            (candles["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range / candles["close"].replace(0, pd.NA)


def load_market_candles(output_dir: Path, market_symbol: str, timeframe: str) -> pd.DataFrame:
    """Load the saved broad-market candles used for the current regime label."""

    path = output_dir / f"webull_{market_symbol.upper()}_{timeframe.upper()}_candles.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return load_candles_from_csv(path, market_symbol.upper())
    except (FileNotFoundError, ValueError):
        return pd.DataFrame()


def classify_regime(candles: pd.DataFrame, scanner: pd.DataFrame) -> dict[str, Any]:
    """Classify current market regime using saved market candles and scanner context."""

    if candles.empty:
        return {
            "market_regime": "unknown",
            "volatility_regime": "unknown",
            "strategy_environment": "unknown",
            "confidence": "low",
            "reason": "No broad-market candles were available for regime detection.",
            "latest_bar_et": "",
        }

    market = add_core_indicators(
        candles,
        fast_length=STRATEGY.fast_ema_length,
        slow_length=STRATEGY.slow_ema_length,
        regime_length=STRATEGY.regime_ema_length,
    ).copy()
    fast = f"ema_{STRATEGY.fast_ema_length}"
    slow = f"ema_{STRATEGY.slow_ema_length}"
    latest = market.iloc[-1]
    latest_time = market.index[-1]

    close = float(latest["close"])
    above_vwap = bool(close > float(latest["vwap"]))
    bullish_stack = bool(float(latest[fast]) > float(latest[slow]))
    bearish_stack = bool(float(latest[fast]) < float(latest[slow]))
    above_regime_ema = bool(close > float(latest[f"ema_{STRATEGY.regime_ema_length}"]))

    recent = market.tail(6)
    recent_return = float((recent["close"].iloc[-1] / recent["open"].iloc[0]) - 1) if len(recent) >= 2 else 0.0
    trend_score = sum([above_vwap, bullish_stack, above_regime_ema])
    bearish_score = sum([not above_vwap, bearish_stack, not above_regime_ema])

    if trend_score >= 3 and recent_return > 0:
        market_regime = "bullish_trend"
    elif bearish_score >= 3 and recent_return < 0:
        market_regime = "bearish_trend"
    elif abs(recent_return) >= 0.006 and (trend_score >= 2 or bearish_score >= 2):
        market_regime = "gap_and_go"
    elif trend_score == 2 or bearish_score == 2:
        market_regime = "mixed_chop"
    else:
        market_regime = "range_chop"

    market["true_range_pct"] = true_range_percent(market).fillna(0.0)
    rolling_median = float(market["true_range_pct"].tail(80).median() or 0.0)
    current_range = float(market["true_range_pct"].iloc[-1] or 0.0)
    if rolling_median <= 0:
        volatility_regime = "unknown"
    elif current_range > rolling_median * 1.35:
        volatility_regime = "high_volatility"
    elif current_range < rolling_median * 0.70:
        volatility_regime = "low_volatility"
    else:
        volatility_regime = "normal_volatility"

    allowed = 0
    not_ready = 0
    if not scanner.empty and "scanner_status" in scanner.columns:
        allowed = int((scanner["scanner_status"] == "allowed").sum())
        not_ready = int((scanner["scanner_status"] == "not_ready").sum())

    if market_regime in {"bullish_trend", "bearish_trend", "gap_and_go"}:
        strategy_environment = "trend_friendly"
    elif market_regime in {"mixed_chop", "range_chop"}:
        strategy_environment = "mean_reversion_research"
    else:
        strategy_environment = "stand_aside"

    confidence = "medium"
    if volatility_regime == "unknown" or len(market) < 80:
        confidence = "low"
    elif allowed > 0 and strategy_environment == "trend_friendly":
        confidence = "medium_high"
    elif not_ready >= 5 and strategy_environment == "mean_reversion_research":
        confidence = "medium"

    reasons = [
        f"SPY close is {'above' if above_vwap else 'below'} VWAP.",
        f"EMA stack is {'bullish' if bullish_stack else 'bearish' if bearish_stack else 'mixed'}.",
        f"Recent 6-bar return is {recent_return:+.2%}.",
        f"Scanner allowed rows: {allowed}; not-ready rows: {not_ready}.",
    ]

    return {
        "market_regime": market_regime,
        "volatility_regime": volatility_regime,
        "strategy_environment": strategy_environment,
        "confidence": confidence,
        "reason": " ".join(reasons),
        "latest_bar_et": latest_time.tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M %Z")
        if getattr(latest_time, "tzinfo", None)
        else str(latest_time),
        "recent_return_pct": round(recent_return * 100, 4),
        "current_true_range_pct": round(current_range * 100, 4),
        "rolling_true_range_pct": round(rolling_median * 100, 4),
    }


def mean_reversion_evidence(output_dir: Path) -> dict[str, Any]:
    """Summarize the latest VWAP mean-reversion research review."""

    summary = read_csv_or_empty(output_dir / "vwap_mean_reversion_summary.csv")
    walk_forward = read_csv_or_empty(output_dir / "vwap_mean_reversion_walk_forward.csv")
    shadow = read_csv_or_empty(output_dir / "vwap_mean_reversion_shadow_outcomes.csv")
    forward = read_csv_or_empty(output_dir / "vwap_mean_reversion_forward_observation_results.csv")
    gate = read_json_or_empty(output_dir / "vwap_mean_reversion_paper_watch_gate.json")
    if summary.empty:
        return {
            "evidence_status": "missing",
            "tightened_pass_rows": 0,
            "promising_rows": 0,
            "best_symbols": "",
            "walk_forward_holding_rows": 0,
            "walk_forward_status": "missing",
            "shadow_samples": 0,
            "matured_shadow_samples": 0,
            "shadow_average_r": 0.0,
            "forward_observations": 0,
            "matured_forward_observations": 0,
            "forward_average_r": 0.0,
            "paper_watch_decision": "missing",
            "paper_watch_blocker": "Run paper-watch gate.",
            "paper_watch_blocked_count": 0,
            "evidence_note": "Run python run_vwap_mean_reversion.py --output-dir logs.",
        }
    pass_rows = (
        summary[summary["tightened_review"] == "passes_tightened_research"].copy()
        if "tightened_review" in summary.columns
        else pd.DataFrame()
    )
    promising = (
        summary[summary["research_status"].isin(["promising", "watch_more"])].copy()
        if "research_status" in summary.columns
        else pd.DataFrame()
    )
    best_symbols = ", ".join(
        pass_rows.sort_values(["expectancy_r", "trades"], ascending=[False, False])["symbol"].astype(str).head(5)
    )
    if not pass_rows.empty:
        status = "tightened_first_review_pass"
        note = f"{len(pass_rows)} row(s) passed tightened first review: {best_symbols}."
    elif not promising.empty:
        status = "promising_needs_more_evidence"
        note = f"{len(promising)} row(s) are promising/watch-more but no row passed tightened review."
    else:
        status = "not_ready"
        note = "No mean-reversion row passed the current research floors."

    holding_rows = (
        walk_forward[walk_forward["decision"] == "holding_up"].copy()
        if not walk_forward.empty and "decision" in walk_forward.columns
        else pd.DataFrame()
    )
    fading_rows = (
        walk_forward[walk_forward["decision"] == "fading"].copy()
        if not walk_forward.empty and "decision" in walk_forward.columns
        else pd.DataFrame()
    )
    if walk_forward.empty:
        walk_status = "missing"
        note = f"{note} Walk-forward review has not run yet."
    elif not holding_rows.empty:
        walk_status = "holding_up"
        sorted_holding = holding_rows.sort_values(["newer_expectancy_r", "full_trades"], ascending=[False, False])
        holding_symbols = ", ".join(dict.fromkeys(sorted_holding["symbol"].astype(str).head(8)).keys())
        note = f"{note} Walk-forward holding up: {holding_symbols}."
    elif not fading_rows.empty:
        walk_status = "fading"
        note = f"{note} Walk-forward warning: at least one newer half is fading."
    else:
        walk_status = "needs_more_sample"
        note = f"{note} Walk-forward still needs more sample."

    matured_shadow = (
        shadow[shadow["evaluation_status"] == "matured"].copy()
        if not shadow.empty and "evaluation_status" in shadow.columns
        else pd.DataFrame()
    )
    if not matured_shadow.empty and "hypothetical_r" in matured_shadow.columns:
        shadow_values = pd.to_numeric(matured_shadow["hypothetical_r"], errors="coerce").dropna()
        shadow_average = round(float(shadow_values.mean()), 4) if not shadow_values.empty else 0.0
    else:
        shadow_average = 0.0
    if shadow.empty:
        note = f"{note} Mean-reversion shadow lane has not collected samples yet."
    else:
        note = f"{note} Mean-reversion shadow samples: {len(shadow)} logged, {len(matured_shadow)} matured, {shadow_average:+.2f}R avg."

    matured_forward = (
        forward[forward["evaluation_status"] == "matured"].copy()
        if not forward.empty and "evaluation_status" in forward.columns
        else pd.DataFrame()
    )
    if not matured_forward.empty and "hypothetical_r" in matured_forward.columns:
        forward_values = pd.to_numeric(matured_forward["hypothetical_r"], errors="coerce").dropna()
        forward_average = round(float(forward_values.mean()), 4) if not forward_values.empty else 0.0
    else:
        forward_average = 0.0
    if forward.empty:
        note = f"{note} Forward observation lane has not collected samples yet."
    else:
        note = f"{note} Forward observations: {len(forward)} logged, {len(matured_forward)} matured, {forward_average:+.2f}R avg."
    gate_decision = str(gate.get("decision", "missing") or "missing")
    gate_blocker = str(gate.get("next_blocker", "Run paper-watch gate.") or "Run paper-watch gate.")
    gate_blocked_count = int(gate.get("blocked_count", 0) or 0)
    if gate_decision == "paper_watch_eligible":
        note = f"{note} Paper-watch gate: eligible for manual review."
    elif gate_decision != "missing":
        note = f"{note} Paper-watch gate: {gate_decision}; next blocker: {gate_blocker}."
    else:
        note = f"{note} Paper-watch gate has not run yet."
    return {
        "evidence_status": status,
        "tightened_pass_rows": int(len(pass_rows)),
        "promising_rows": int(len(promising)),
        "best_symbols": best_symbols,
        "walk_forward_holding_rows": int(len(holding_rows)),
        "walk_forward_status": walk_status,
        "shadow_samples": int(len(shadow)),
        "matured_shadow_samples": int(len(matured_shadow)),
        "shadow_average_r": shadow_average,
        "forward_observations": int(len(forward)),
        "matured_forward_observations": int(len(matured_forward)),
        "forward_average_r": forward_average,
        "paper_watch_decision": gate_decision,
        "paper_watch_blocker": gate_blocker,
        "paper_watch_blocked_count": gate_blocked_count,
        "evidence_note": note,
    }


def evidence_for_strategy(strategy: VaultStrategy, output_dir: Path) -> dict[str, Any]:
    """Return strategy-specific evidence metadata for routing."""

    if strategy.strategy_id == "vwap_mean_reversion":
        return mean_reversion_evidence(output_dir)
    return {
        "evidence_status": "existing_or_not_applicable",
        "tightened_pass_rows": 0,
        "promising_rows": 0,
        "best_symbols": "",
        "walk_forward_holding_rows": 0,
        "walk_forward_status": "not_applicable",
        "shadow_samples": 0,
        "matured_shadow_samples": 0,
        "shadow_average_r": 0.0,
        "forward_observations": 0,
        "matured_forward_observations": 0,
        "forward_average_r": 0.0,
        "paper_watch_decision": "not_applicable",
        "paper_watch_blocker": "",
        "paper_watch_blocked_count": 0,
        "evidence_note": strategy.evidence_source,
    }


def strategy_decision(strategy: VaultStrategy, regime: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Rank one strategy for the current regime."""

    market_regime = str(regime.get("market_regime", "unknown"))
    volatility_regime = str(regime.get("volatility_regime", "unknown"))
    status = strategy.status
    evidence = evidence_for_strategy(strategy, output_dir)

    score = 0
    reasons = []
    if market_regime in strategy.ideal_regimes:
        score += 3
        reasons.append(f"Market regime matches ideal: {market_regime}.")
    elif market_regime in strategy.caution_regimes:
        score -= 2
        reasons.append(f"Market regime is cautionary: {market_regime}.")
    else:
        reasons.append(f"Market regime is not a primary match: {market_regime}.")

    if volatility_regime in strategy.ideal_volatility:
        score += 1
        reasons.append(f"Volatility is acceptable: {volatility_regime}.")
    elif volatility_regime != "unknown":
        score -= 1
        reasons.append(f"Volatility is not ideal: {volatility_regime}.")

    if status == "active_paper_watch" and score >= 3:
        decision = "active"
        action = "Use existing scanner/paper gates. Review only current-candle size-ok candidates."
    elif status == "active_paper_watch" and score >= 1:
        decision = "watch"
        action = "Keep scanning, but be selective. Do not force entries in mixed conditions."
    elif status == "active_paper_watch":
        decision = "caution"
        action = "Current trend-continuation strategy is not favored. Stand aside unless the scanner produces a perfect fresh setup."
    elif score >= 2:
        decision = "research_priority"
        action = strategy.next_research_step
    else:
        decision = "research_backlog"
        action = "Keep in vault, but do not prioritize today."

    if strategy.strategy_id == "vwap_mean_reversion" and evidence["tightened_pass_rows"] > 0 and decision == "research_priority":
        if evidence["walk_forward_status"] == "holding_up":
            action = (
                f"{evidence['evidence_note']} Next: collect strategy-specific shadow samples and forward "
                "observations before paper-watch promotion."
            )
        else:
            action = (
                f"{evidence['evidence_note']} Next: run walk-forward, strategy-specific shadow samples, "
                "and forward observation before paper-watch promotion."
            )

    return {
        "strategy_id": strategy.strategy_id,
        "name": strategy.name,
        "status": status,
        "family": strategy.family,
        "decision": decision,
        "score": score,
        "action": action,
        "description": strategy.description,
        "evidence_source": strategy.evidence_source,
        "evidence_status": evidence["evidence_status"],
        "tightened_pass_rows": evidence["tightened_pass_rows"],
        "promising_rows": evidence["promising_rows"],
        "best_symbols": evidence["best_symbols"],
        "walk_forward_holding_rows": evidence["walk_forward_holding_rows"],
        "walk_forward_status": evidence["walk_forward_status"],
        "shadow_samples": evidence["shadow_samples"],
        "matured_shadow_samples": evidence["matured_shadow_samples"],
        "shadow_average_r": evidence["shadow_average_r"],
        "forward_observations": evidence["forward_observations"],
        "matured_forward_observations": evidence["matured_forward_observations"],
        "forward_average_r": evidence["forward_average_r"],
        "paper_watch_decision": evidence["paper_watch_decision"],
        "paper_watch_blocker": evidence["paper_watch_blocker"],
        "paper_watch_blocked_count": evidence["paper_watch_blocked_count"],
        "evidence_note": evidence["evidence_note"],
        "next_research_step": strategy.next_research_step,
        "reason": " ".join(reasons),
    }


def build_payload(output_dir: Path, market_symbol: str, timeframe: str) -> dict[str, Any]:
    """Build the complete strategy vault payload."""

    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    candles = load_market_candles(output_dir, market_symbol, timeframe)
    regime = classify_regime(candles, scanner)
    strategies = [strategy_decision(strategy, regime, output_dir) for strategy in STRATEGY_VAULT]
    strategies = sorted(strategies, key=lambda row: (row["decision"] != "active", -row["score"], row["name"]))
    active = [row for row in strategies if row["decision"] == "active"]
    research_priority = [row for row in strategies if row["decision"] == "research_priority"]
    if active:
        next_action = active[0]["action"]
    elif research_priority:
        next_action = f"Prioritize research: {research_priority[0]['name']}. {research_priority[0]['action']}"
    else:
        next_action = "No strategy is favored strongly. Keep collecting evidence and avoid forced paper entries."

    return {
        "market_symbol": market_symbol.upper(),
        "timeframe": timeframe.upper(),
        "regime": regime,
        "active_strategy_count": len(active),
        "research_priority_count": len(research_priority),
        "next_action": next_action,
        "guardrail": "Strategy vault routes research attention only. It does not approve trades or bypass paper gates.",
        "strategies": strategies,
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write strategy vault JSON, CSV, and Markdown reports."""

    json_path = output_dir / "strategy_vault.json"
    csv_path = output_dir / "strategy_vault.csv"
    md_path = output_dir / "strategy_vault.md"

    rows = pd.DataFrame(payload["strategies"])
    rows.to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    regime = payload["regime"]
    md_path.write_text(
        f"""# Strategy Vault

This report selects which strategy family deserves attention under the current
market backdrop. It is research and manual paper-review guidance only.

Important: it does not approve trades, import paper entries, place broker
orders, create broker alerts, or bypass the existing scanner/sizing gates.

## Current Regime

{markdown_table(pd.DataFrame([regime]))}

## Next Action

```text
{payload["next_action"]}
```

## Strategy Routing

{markdown_table(rows)}

## Guardrail

```text
{payload["guardrail"]}
```

## Files

```text
logs/strategy_vault.json
logs/strategy_vault.csv
logs/strategy_vault.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload(args.output_dir, args.market_symbol, args.timeframe)
    write_outputs(args.output_dir, payload)
    print(f"Saved strategy vault JSON: {args.output_dir / 'strategy_vault.json'}")
    print(f"Saved strategy vault CSV: {args.output_dir / 'strategy_vault.csv'}")
    print(f"Saved strategy vault report: {args.output_dir / 'strategy_vault.md'}")


if __name__ == "__main__":
    main()

"""Research universes for broad backtest expansion.

These lists are intentionally separate from the approved playbook. A symbol
appearing here is only a research candidate until it survives backtesting and
forward paper validation.
"""

from __future__ import annotations


CORE_RESEARCH_SYMBOLS = [
    "SPY",
    "QQQ",
    "NVDA",
    "TSLA",
    "AMD",
    "AAPL",
    "META",
    "MSFT",
]


LIQUID_OPTIONS_RESEARCH_SYMBOLS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMD",
    "META",
    "AMZN",
    "GOOGL",
    "NFLX",
    "AVGO",
    "COIN",
    "PLTR",
    "MARA",
    "SMCI",
    "BABA",
    "JPM",
    "BAC",
    "GS",
    "XOM",
    "CVX",
    "UNH",
    "LLY",
    "MRNA",
    "BA",
    "CAT",
    "DE",
    "COST",
    "WMT",
    "DIS",
    "NKE",
    "SHOP",
    "UBER",
    "SNOW",
    "CRM",
    "ADBE",
    "PYPL",
]


RESEARCH_UNIVERSES = {
    "core": CORE_RESEARCH_SYMBOLS,
    "liquid_options": LIQUID_OPTIONS_RESEARCH_SYMBOLS,
}

"""Project settings.

These values are intentionally simple and visible. A beginner should be able to
change the strategy behavior from this file without digging through the engine.
"""

from dataclasses import dataclass


@dataclass
class StrategySettings:
    """Rules for the first VWAP + EMA trend continuation strategy."""

    # Execution timeframe. The current data source uses this interval directly.
    execution_interval: str = "30m"
    exit_interval: str = "5m"

    # Higher timeframe used to build the trading thesis.
    thesis_interval: str = "60m"
    require_higher_timeframe_bias: bool = True

    # Session rules use New York time because US equities trade on that clock.
    market_timezone: str = "America/New_York"
    market_open: str = "09:30"
    market_close: str = "16:00"
    entry_start_time: str = "10:00"
    latest_entry_time: str = "15:15"
    force_exit_time: str = "15:55"

    # Opening range filter. The first 30 minutes often define the early battle
    # line between buyers and sellers.
    opening_range_minutes: int = 30
    require_above_opening_range: bool = True

    # "Top-tier style" quality filters. These do not predict; they force
    # selectivity by requiring volume, trend, clean structure, and room to target.
    relative_volume_lookback: int = 20
    min_relative_volume: float = 1.2
    resistance_lookback: int = 20
    min_room_to_resistance_r: float = 1.25
    elite_min_score: int = 8

    # Indicator lengths. These mirror the user's discretionary tools.
    fast_ema_length: int = 9
    slow_ema_length: int = 21
    regime_ema_length: int = 200

    # Entry behavior.
    require_above_vwap: bool = True
    require_fast_above_slow: bool = True
    require_above_regime_ema: bool = True

    # Risk/reward model. 2R means target is twice the distance of the stop.
    stop_buffer_pct: float = 0.001
    reward_multiple: float = 2.0

    # Trading day safety limits.
    max_trades_per_day: int = 3
    max_consecutive_losses: int = 2
    max_daily_loss_r: float = -2.0


@dataclass
class AccountSettings:
    """Backtest account assumptions.

    The framework tracks R-multiple performance first because R keeps the
    research focused on strategy quality instead of account size.
    """

    starting_equity: float = 10_000.0
    risk_per_trade_pct: float = 0.005


STRATEGY = StrategySettings()
ACCOUNT = AccountSettings()

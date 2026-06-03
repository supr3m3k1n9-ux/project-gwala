"""Print Project Gwala's local NYSE market calendar view."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date
from config.settings import STRATEGY
from run_intraday_loop import parse_clock
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show local NYSE market calendar sessions.")
    parser.add_argument("--start", help="Start date YYYY-MM-DD. Defaults to today in New York.")
    parser.add_argument("--days", type=int, default=10, help="Number of calendar days to show.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = datetime.now(tz=MARKET_TZ).date() if not args.start else pd.to_datetime(args.start).date()
    market_open = parse_clock(STRATEGY.market_open)
    market_close = parse_clock(STRATEGY.market_close)

    rows = []
    for offset in range(args.days):
        session = market_session_for_date(start + timedelta(days=offset), market_open, market_close)
        rows.append(
            {
                "date": str(session.session_date),
                "market_day": session.is_market_day,
                "open_et": "" if session.market_open is None else session.market_open.strftime("%H:%M"),
                "close_et": "" if session.market_close is None else session.market_close.strftime("%H:%M"),
                "early_close": session.is_early_close,
                "reason": session.reason,
            }
        )

    print(markdown_table(pd.DataFrame(rows)))


if __name__ == "__main__":
    main()

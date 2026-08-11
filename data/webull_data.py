"""Webull OpenAPI market-data helpers.

This module is intentionally data-only. It does not import trading/order
clients and it does not place, modify, or cancel orders.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
from types import MethodType
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
TOKEN_DIR = PROJECT_ROOT / ".webull_tokens"


def load_env_file(path: Path = ENV_PATH) -> None:
    """Load simple KEY=value lines without requiring python-dotenv."""

    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def require_env(name: str) -> str:
    """Return an environment value or stop with a beginner-friendly message."""

    value = os.environ.get(name, "").strip()
    if not value or value.startswith("your_"):
        raise SystemExit(f"Missing {name}. Add it to .env before running Webull data tools.")
    return value


def disable_sdk_default_logging(api_client: Any) -> None:
    """Prevent Webull SDK default stdout/file logging.

    The SDK's DataClient creates `webull_data_sdk.log` in the current working
    directory unless it sees that logging was already configured. That file can
    include signed request/response diagnostics, so Gwala disables the default
    SDK log handlers instead of making the application source directory
    writable.
    """

    null_logger = logging.getLogger("webull.gwala.disabled")
    null_logger.handlers = [handler for handler in null_logger.handlers if isinstance(handler, logging.NullHandler)]
    if not any(isinstance(handler, logging.NullHandler) for handler in null_logger.handlers):
        null_logger.addHandler(logging.NullHandler())
    null_logger.propagate = False

    set_logger = getattr(api_client, "set_logger", None)
    if callable(set_logger):
        set_logger(null_logger)

    setattr(api_client, "_stream_logger_set", True)
    setattr(api_client, "_file_logger_set", True)
    for logger_name in ("webull.core", "webull.data"):
        logger = logging.getLogger(logger_name)
        logger.handlers = [handler for handler in logger.handlers if isinstance(handler, logging.NullHandler)]
        if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
            logger.addHandler(logging.NullHandler())
        logger.propagate = False

    def disabled_stream_logger(self: Any, *args: Any, **kwargs: Any) -> None:
        self._stream_logger_set = True

    def disabled_file_logger(self: Any, *args: Any, **kwargs: Any) -> None:
        self._file_logger_set = True

    api_client.set_stream_logger = MethodType(disabled_stream_logger, api_client)
    api_client.set_file_logger = MethodType(disabled_file_logger, api_client)


def build_data_client() -> Any:
    """Create a Webull data client from local `.env` credentials."""

    load_env_file()

    # The Webull SDK can log signed request headers during failures. Keep these
    # data tools quiet so API tokens and signatures are not printed.
    logging.disable(logging.CRITICAL)

    app_key = require_env("WEBULL_APP_KEY")
    app_secret = require_env("WEBULL_APP_SECRET")
    region_id = os.environ.get("WEBULL_REGION_ID", "us").strip() or "us"
    optional_endpoint = os.environ.get("WEBULL_API_ENDPOINT", "").strip()

    try:
        from webull.core.client import ApiClient
        from webull.data.data_client import DataClient
    except ImportError as exc:
        raise SystemExit(
            "Webull SDK is not installed in this Python environment.\n"
            "Use the Python 3.11 environment:\n"
            "  source .venv-webull/bin/activate\n"
            "  pip install -r requirements-webull.txt"
        ) from exc

    TOKEN_DIR.mkdir(parents=True, exist_ok=True)

    api_client = ApiClient(app_key, app_secret, region_id)
    api_client.set_token_dir(str(TOKEN_DIR))
    disable_sdk_default_logging(api_client)

    if optional_endpoint:
        api_client.add_endpoint(region_id, optional_endpoint)

    return DataClient(api_client)


def fetch_history_bars(
    data_client: Any,
    symbol: str,
    timespan: str,
    count: int,
    trading_sessions: list[str],
    end_time: int | None = None,
) -> list[dict]:
    """Fetch historical bars from Webull as raw dictionaries."""

    try:
        from webull.data.common.category import Category
        from webull.data.common.timespan import Timespan
        from webull.data.request.get_historical_bars_request import GetHistoricalBarsRequest
    except ImportError as exc:
        raise SystemExit("Webull SDK is not installed in this Python environment.") from exc

    try:
        request = GetHistoricalBarsRequest()
        request.set_symbol(symbol.upper())
        request.set_category(Category.US_STOCK.name)
        request.set_timespan(getattr(Timespan, timespan).name)
        request.set_count(str(count))
        request.set_trading_sessions(trading_sessions)
        request.set_end_time(end_time)
        request.set_connect_timeout(10)
        request.set_read_timeout(30)
        response = data_client.market_data.client.get_response(request)
    except Exception as exc:
        message = str(exc)
        if "Insufficient permission" in message:
            raise RuntimeError("Insufficient Webull market-data permission. Check quote subscriptions.") from exc
        if "TOO_MANY_REQUESTS" in message or "429" in message:
            raise RuntimeError("Webull rate limit hit. Wait and retry with longer pauses.") from exc
        raise RuntimeError(f"Webull request failed: {type(exc).__name__}") from exc

    if response.status_code != 200:
        raise RuntimeError(f"Webull returned HTTP {response.status_code}.")

    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Webull returned an unexpected response shape.")

    return payload


def candle_time_ms(row: dict) -> int:
    """Convert a Webull candle time string into epoch milliseconds."""

    import pandas as pd

    timestamp = pd.to_datetime(row["time"], utc=True)
    return int(timestamp.timestamp() * 1000)


def fetch_history_bars_paged(
    data_client: Any,
    symbol: str,
    timespan: str,
    count: int,
    pages: int,
    trading_sessions: list[str],
    pause_seconds: float,
) -> list[dict]:
    """Fetch multiple older Webull history pages and deduplicate candles.

    Webull returns newest candles first. To page backward, each next request
    ends one millisecond before the oldest candle from the previous request.
    """

    all_rows_by_time = {}
    end_time = None

    for page_number in range(1, pages + 1):
        print(f"{symbol.upper()} {timespan}: fetching page {page_number}/{pages}", flush=True)
        rows = fetch_history_bars(
            data_client=data_client,
            symbol=symbol,
            timespan=timespan,
            count=count,
            trading_sessions=trading_sessions,
            end_time=end_time,
        )
        if not rows:
            break

        for row in rows:
            all_rows_by_time[row["time"]] = row

        oldest_row = min(rows, key=candle_time_ms)
        end_time = candle_time_ms(oldest_row) - 1

        if len(rows) < count:
            break

        if page_number < pages and pause_seconds > 0:
            import time

            time.sleep(pause_seconds)

    return [all_rows_by_time[key] for key in sorted(all_rows_by_time)]


def write_raw_json(payload: list[dict], output_path: Path) -> None:
    """Save the raw Webull response for debugging and auditability."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def write_backtest_csv(rows: list[dict], output_path: Path) -> None:
    """Save Webull bars in the standard backtester candle format."""

    candles = []
    for row in rows:
        candles.append(
            {
                "datetime": row["time"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
        )

    candles.sort(key=lambda candle: candle["datetime"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["datetime", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        writer.writerows(candles)


def print_safe_webull_error(error: Exception) -> None:
    """Print Webull failures without exposing signed request headers."""

    print("Webull request failed.")
    print(str(error))
    print("Details were hidden to avoid exposing API tokens or signed headers.")
    sys.exit(1)

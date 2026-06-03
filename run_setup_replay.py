"""Build historical setup replay drills from approved playbook trades.

This is practice mode for non-market hours. It turns historical simulated
trades into small replay cards so the user can rehearse entry, stop, target,
exit, and checklist thinking.

It does not fetch data, place orders, create alerts, or connect to broker
execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from run_playbook import markdown_table


RECOMMENDATION_CHECKLIST = [
    "Review one winning and one losing replay before the next market open.",
    "Say the entry, stop, target, and invalidation out loud before checking the result.",
    "Use replay mode to practice checklist discipline, not to predict future trades.",
    "Refresh Webull data during market hours before acting on live scanner rows.",
    "Continue paper validation toward the 30-trade checkpoint.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build setup replay practice drills.")
    parser.add_argument(
        "--trades-csv",
        type=Path,
        default=Path("logs/playbook_approved_trades.csv"),
        help="Approved playbook trade log.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where replay reports are saved.")
    parser.add_argument("--limit", type=int, default=20, help="Number of replay cards to write.")
    return parser.parse_args()


def read_trades(path: Path) -> pd.DataFrame:
    """Read approved playbook trades."""

    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def classify_result(r_result: float) -> str:
    """Return a plain-English result bucket."""

    if r_result >= 1:
        return "strong_win"
    if r_result > 0:
        return "small_win"
    if r_result == 0:
        return "flat"
    if r_result > -1:
        return "managed_loss"
    return "full_loss"


def plan_prompts(row: pd.Series) -> list[str]:
    """Create prompts that are safe to show before revealing the outcome."""

    prompts = []
    direction = str(row.get("playbook_direction", ""))
    setup = str(row.get("playbook_setup", ""))

    prompts.append(f"Direction is {direction}; check whether the stop and target match that direction.")
    prompts.append(f"Setup is {setup}; identify the VWAP/EMA trend-continuation idea before revealing the outcome.")

    if bool(row.get("strong_relative_volume", False)):
        prompts.append("Relative volume is strong; decide whether that supports taking this setup.")
    else:
        prompts.append("Relative volume is not strong; decide whether the setup still meets your checklist.")

    prompts.append("Before revealing, state whether you would take, skip, or watch this historical setup.")
    return prompts


def outcome_review_prompts(row: pd.Series) -> list[str]:
    """Create prompts to use only after the historical outcome is revealed."""

    prompts = []
    r_result = float(row.get("r_result", 0))
    prompts.append(f"Risk result was {r_result:.2f}R; compare the exit reason with the planned target and stop.")

    if r_result < 0:
        prompts.append("This was a loss or managed loss; practice accepting the planned stop without adjustment.")
    else:
        prompts.append("This was a win; practice whether you would have followed the exit plan without over-managing.")

    return prompts


def build_replays(trades: pd.DataFrame, limit: int) -> list[dict]:
    """Build replay cards from a balanced slice of recent historical trades."""

    if trades.empty:
        return []

    result = trades.copy()
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True)
    result["r_result"] = result["r_result"].astype(float)

    winners = result[result["r_result"] > 0].tail(max(limit // 2, 1))
    losers = result[result["r_result"] <= 0].tail(max(limit - len(winners), 1))
    sample = pd.concat([winners, losers], ignore_index=True).sort_values("entry_time").tail(limit)

    cards = []
    for index, (_, row) in enumerate(sample.iterrows(), start=1):
        cards.append(
            {
                "replay_id": index,
                "symbol": str(row.get("symbol", "")),
                "setup": str(row.get("playbook_setup", "")),
                "direction": str(row.get("playbook_direction", "")),
                "variant": str(row.get("playbook_variant", "")),
                "exit_profile": str(row.get("playbook_exit_profile", "")),
                "entry_time": str(row.get("entry_time", "")),
                "exit_time": str(row.get("exit_time", "")),
                "entry": round(float(row.get("entry", 0)), 4),
                "stop": round(float(row.get("stop", 0)), 4),
                "target": round(float(row.get("target", 0)), 4),
                "exit_price": round(float(row.get("exit_price", 0)), 4),
                "r_result": round(float(row.get("r_result", 0)), 4),
                "result_type": classify_result(float(row.get("r_result", 0))),
                "exit_reason": str(row.get("exit_reason", "")),
                "quality_grade": str(row.get("quality_grade", "")),
                "quality_score": int(row.get("quality_score", 0)),
                "relative_volume": round(float(row.get("relative_volume", 0)), 4),
                "room_to_target_r": round(float(row.get("room_to_resistance_r", 0)), 4),
                "notes": str(row.get("playbook_notes", "")),
                "plan_prompts": plan_prompts(row),
                "outcome_review_prompts": outcome_review_prompts(row),
            }
        )
    return cards


def write_markdown(path: Path, cards: list[dict]) -> None:
    """Write a readable replay report."""

    rows = [
        {
            "id": card["replay_id"],
            "symbol": card["symbol"],
            "setup": card["setup"],
            "direction": card["direction"],
            "entry_time": card["entry_time"],
            "r_result": card["r_result"],
            "exit_reason": card["exit_reason"],
            "result_type": card["result_type"],
        }
        for card in cards
    ]
    checklist = "\n".join(f"- [ ] {item}" for item in RECOMMENDATION_CHECKLIST)

    path.write_text(
        f"""# Setup Replay Practice

This is non-market-hours practice mode built from historical approved playbook
trades.

Important: this is research/paper workflow only. It does not fetch data, place
orders, create alerts, or connect to broker execution.

The local app starts each replay with its historical result concealed so you
can make a process decision before choosing to reveal the outcome. This
Markdown table remains an audit record and therefore includes outcomes.

## Replay Cards

{markdown_table(pd.DataFrame(rows))}

## Practice Checklist

{checklist}

## Files

```text
logs/setup_replay.json
logs/setup_replay.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    cards = build_replays(read_trades(args.trades_csv), args.limit)
    payload = {
        "source": str(args.trades_csv),
        "count": len(cards),
        "cards": cards,
    }

    json_path = args.output_dir / "setup_replay.json"
    md_path = args.output_dir / "setup_replay.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_markdown(md_path, cards)

    print(f"Saved setup replay JSON: {json_path}")
    print(f"Saved setup replay report: {md_path}")


if __name__ == "__main__":
    main()

"""Build official paper-entry packets for ready current candidates.

This report makes the last manual step clearer: which candidates are eligible
for local paper review, what would be logged, and which command previews or
confirms the local paper entry. It does not write paper trades, place broker
orders, create alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table


PACKET_COLUMNS = [
    "symbol",
    "setup",
    "direction",
    "signal_time_et",
    "signal_freshness",
    "validation_lane",
    "suggested_shares",
    "risk_guard_status",
    "router_route",
    "paper_preview_command",
    "paper_confirm_command",
    "manual_review_status",
    "notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local paper-entry review packets.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where workflow outputs live.")
    return parser.parse_args()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read JSON or return an empty dict."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def text_value(value: object) -> str:
    """Return stable display text."""

    if value is None or pd.isna(value):
        return ""
    return str(value)


def build_packets(output_dir: Path = Path("logs")) -> dict[str, Any]:
    """Build packet payload from pre-entry review and system state."""

    pre_entry = read_json_or_empty(output_dir / "pre_entry_review.json")
    rows = pre_entry.get("rows", []) if isinstance(pre_entry.get("rows", []), list) else []
    review = pd.DataFrame(rows)
    state = read_json_or_empty(output_dir / "system_state.json")
    data_flow = state.get("data_flow_sentinel", {}) if isinstance(state.get("data_flow_sentinel"), dict) else {}
    provider = state.get("provider_stability_audit", {}) if isinstance(state.get("provider_stability_audit"), dict) else {}
    market = state.get("market", {}) if isinstance(state.get("market"), dict) else {}
    freshness = state.get("data_freshness", {}) if isinstance(state.get("data_freshness"), dict) else {}
    readiness = str(state.get("readiness_verdict", ""))
    actionable_session = bool(market.get("market_is_open")) and freshness.get("data_status") == "fresh_for_today"

    if review.empty or "review_status" not in review.columns or not actionable_session:
        ready = pd.DataFrame(columns=PACKET_COLUMNS)
        b_tier_manual_only = 0
    else:
        ready_rows = review[review["review_status"].astype(str) == "ready_for_manual_review"].copy()
        if "signal_freshness" not in ready_rows.columns:
            ready_rows["signal_freshness"] = ""
        if "validation_lane" not in ready_rows.columns:
            ready_rows["validation_lane"] = ""
        b_tier_manual_only = int(
            (
                ready_rows["signal_freshness"].astype(str).eq("grace_candle")
                | ready_rows["validation_lane"].astype(str).str.upper().eq("B")
            ).sum()
        )
        ready_rows = ready_rows[
            ready_rows["signal_freshness"].astype(str).eq("current_candle")
            & ~ready_rows["validation_lane"].astype(str).str.upper().eq("B")
        ].copy()
        packets = []
        for _, row in ready_rows.iterrows():
            packets.append(
                {
                    "symbol": text_value(row.get("symbol")),
                    "setup": text_value(row.get("setup")),
                    "direction": text_value(row.get("direction")),
                    "signal_time_et": text_value(row.get("signal_time_et")),
                    "signal_freshness": text_value(row.get("signal_freshness")),
                    "validation_lane": text_value(row.get("validation_lane")) or "A",
                    "suggested_shares": text_value(row.get("suggested_shares")),
                    "risk_guard_status": text_value(row.get("risk_guard_status")),
                    "router_route": text_value(row.get("router_route")),
                    "paper_preview_command": "python run_paper_session_cycle.py",
                    "paper_confirm_command": "python run_paper_session_cycle.py --confirm-local-paper",
                    "manual_review_status": "chart_review_required",
                    "notes": "Preview first. Confirm local paper only after chart, stop, target, and size match the plan.",
                }
            )
        ready = pd.DataFrame(packets, columns=PACKET_COLUMNS)

    blocked = int(pre_entry.get("blocked_candidates", 0) or 0)
    ready_count = int(len(ready))
    data_flow_status = str(data_flow.get("status", "missing"))
    provider_status = str(provider.get("status", "missing"))
    if not actionable_session:
        next_action = freshness.get("action") or readiness or "Run the market-data workflow during the next open session."
    elif ready_count:
        next_action = "Run the local paper preview, manually review the chart/risk, then confirm only if the plan still matches."
    elif b_tier_manual_only:
        next_action = (
            "B-tier grace row(s) require Paper Gate v2, Options Contract Gate, and validation import. "
            "No local paper-entry packet is created for B-tier grace."
        )
    elif blocked:
        next_action = "Review pre-entry blockers; do not log local paper until a packet appears here."
    else:
        next_action = "No review-first candidate is packet-ready. Keep the workflow refreshed."

    return {
        "ready_packet_count": ready_count,
        "b_tier_manual_only_count": b_tier_manual_only,
        "blocked_candidate_count": blocked,
        "data_flow_status": data_flow_status,
        "provider_stability_status": provider_status,
        "actionable_session": actionable_session,
        "readiness_verdict": readiness,
        "next_action": next_action,
        "guardrail": (
            "Packet-ready means A-tier/current-candle manual local paper review only. "
            "B-tier grace rows never receive local entry commands here. No broker orders or real trades."
        ),
        "packets": ready.to_dict("records"),
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write packet JSON, CSV, and Markdown."""

    output_dir.mkdir(parents=True, exist_ok=True)
    packets = pd.DataFrame(payload["packets"], columns=PACKET_COLUMNS)
    (output_dir / "paper_entry_packet.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    packets.to_csv(output_dir / "paper_entry_packet.csv", index=False)
    (output_dir / "paper_entry_packet.md").write_text(
        f"""# Paper Entry Packet

This report packages candidates that passed the pre-entry gate for manual local
paper review.

Important: this report does not write paper trades, place broker orders,
create broker alerts, or connect to broker execution.

## Summary

```text
Ready packets: {payload["ready_packet_count"]}
B-tier manual-only rows: {payload["b_tier_manual_only_count"]}
Blocked candidates: {payload["blocked_candidate_count"]}
Data flow: {payload["data_flow_status"]}
Provider stability: {payload["provider_stability_status"]}
Actionable session: {payload["actionable_session"]}
```

## Next Action

```text
{payload["next_action"]}
```

## Ready Packets

{markdown_table(packets)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload = build_packets(args.output_dir)
    write_outputs(args.output_dir, payload)
    print(f"Paper entry packets ready: {payload['ready_packet_count']}")
    print(f"Saved paper entry packet: {args.output_dir / 'paper_entry_packet.md'}")


if __name__ == "__main__":
    main()

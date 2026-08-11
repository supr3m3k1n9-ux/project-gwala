"""Run the safe local paper-trading cycle.

This is the operator shortcut for the current paper-validation phase. It ties
together candidate alerts, local paper ticket creation, open-paper exit
monitoring, and local report refreshes.

It does not call broker order endpoints, place Webull paper orders, place real
orders, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

import pandas as pd

from run_playbook import markdown_table


PROJECT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class StepResult:
    """One command result for the paper session report."""

    step: str
    status: str
    command: str
    output: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Project Gwala local paper session cycle.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--confirm-local-paper",
        action="store_true",
        help="Write eligible local paper order/trade rows. Defaults to preview only.",
    )
    parser.add_argument(
        "--confirm-exits",
        action="store_true",
        help="Write completed local paper exit updates. Defaults to preview only.",
    )
    return parser.parse_args()


def build_commands(
    output_dir: Path,
    confirm_local_paper: bool = False,
    confirm_exits: bool = False,
    python: str = sys.executable,
) -> list[tuple[str, list[str]]]:
    """Build the ordered safe local paper-cycle commands."""

    local_paper_command = [python, "run_paper_execution_simulator.py", "--output-dir", str(output_dir)]
    if confirm_local_paper:
        local_paper_command.append("--confirm-local-paper")
    open_monitor_command = [python, "run_open_paper_monitor.py", "--output-dir", str(output_dir)]
    if confirm_exits:
        open_monitor_command.append("--confirm-updates")
    commands = [
        ("Candidate alerts", [python, "run_candidate_alerts.py", "--output-dir", str(output_dir)]),
        ("Pre-entry review", [python, "run_pre_entry_review.py", "--output-dir", str(output_dir)]),
        ("Paper entry packet", [python, "run_paper_entry_packet.py", "--output-dir", str(output_dir)]),
        ("Paper Gate v2", [python, "run_paper_gate_v2.py", "--output-dir", str(output_dir)]),
        ("Options Contract Gate", [python, "run_options_contract_gate.py", "--output-dir", str(output_dir)]),
        ("Validation sample import preview", [python, "run_paper_validation_sample_import.py", "--output-dir", str(output_dir)]),
        ("Daily ship report", [python, "run_daily_ship_report.py", "--output-dir", str(output_dir)]),
        ("Filter rejection report", [python, "run_filter_rejection_report.py", "--output-dir", str(output_dir)]),
        ("Local paper execution", local_paper_command),
        ("Open paper monitor", open_monitor_command),
        ("Exit audit", [python, "run_exit_audit.py", "--output-dir", str(output_dir)]),
        ("Paper review", [python, "run_paper_review.py", "--output-dir", str(output_dir)]),
        ("Forward sample queue", [python, "run_forward_sample_queue.py", "--output-dir", str(output_dir)]),
        ("No-trade analysis", [python, "run_no_trade_analysis.py", "--output-dir", str(output_dir)]),
        ("Shadow samples", [python, "run_shadow_samples.py", "--output-dir", str(output_dir)]),
        ("Candidate aging", [python, "run_candidate_aging.py", "--output-dir", str(output_dir)]),
        ("Forward evidence", [python, "run_forward_evidence.py", "--output-dir", str(output_dir)]),
        ("Refresh status", [python, "run_refresh_status.py", "--output-dir", str(output_dir)]),
        ("Dashboard data preflight", [python, "run_dashboard_data_preflight.py", "--output-dir", str(output_dir)]),
        ("Data flow sentinel", [python, "run_data_flow_sentinel.py", "--output-dir", str(output_dir)]),
        ("System state", [python, "run_system_state.py", "--output-dir", str(output_dir)]),
    ]
    return commands


def run_step(step: str, command: list[str]) -> StepResult:
    """Run one local paper-cycle command and capture its output."""

    completed = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = "\n".join(part.strip() for part in [completed.stdout, completed.stderr] if part.strip())
    return StepResult(step=step, status="ok", command=" ".join(command), output=output)


def write_report(
    path: Path,
    results: list[StepResult],
    confirm_local_paper: bool,
    confirm_exits: bool,
) -> None:
    """Write the operator summary for this paper session cycle."""

    rows = pd.DataFrame(
        [
            {
                "step": result.step,
                "status": result.status,
                "command": result.command,
            }
            for result in results
        ]
    )
    output_blocks = "\n\n".join(
        f"### {result.step}\n\n```text\n{result.output or 'No output.'}\n```" for result in results
    )

    path.write_text(
        f"""# Paper Session Cycle

This report summarizes the safe local paper-trading cycle.

Important: this is research and paper-validation only. It does not place
Webull paper orders, place real orders, call broker order endpoints, or connect
to broker execution.

## Run Mode

```text
Confirmed local paper entries: {confirm_local_paper}
Confirmed local paper exits: {confirm_exits}
```

## Steps

{markdown_table(rows)}

## Command Output

{output_blocks}

## Related Reports

```text
logs/paper_candidate_alerts.md
logs/paper_gate_v2.md
logs/options_contract_gate.md
logs/paper_validation_sample_import.md
logs/DAILY_SHIP_REPORT.md
logs/filter_rejection_report.md
logs/local_paper_execution_simulator.md
logs/open_paper_trade_monitor.md
logs/paper_exit_audit.md
logs/forward_sample_queue.md
logs/observation_paper_reconciliation.md
logs/refresh_status.md
logs/dashboard_data_preflight.md
logs/data_flow_sentinel.md
logs/system_state.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for step, command in build_commands(args.output_dir, args.confirm_local_paper, args.confirm_exits):
        print(f"Running: {step}")
        results.append(run_step(step, command))

    report_path = args.output_dir / "paper_session_cycle.md"
    write_report(report_path, results, args.confirm_local_paper, args.confirm_exits)

    print(f"Paper session cycle complete. Saved report: {report_path}")
    if not args.confirm_local_paper:
        print("Preview mode: local paper entries were not written.")
    if not args.confirm_exits:
        print("Preview mode: local paper exits were not written.")


if __name__ == "__main__":
    main()

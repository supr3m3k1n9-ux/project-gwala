"""Phase 3 research activation artifacts.

This module turns the frozen Cohort 1 evidence into an opening Phase 3 research
agenda. It is governance/reporting only: it does not run backtests, change
strategy logic, mutate Cohort 1, activate live trading, or touch broker paths.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from reports.cohort_freeze import COHORT_VERSION
from reports.cohort_freeze import load_cohort_1_freeze


PHASE3_SCHEMA_VERSION = "phase3-activation-v1"


def phase3_dir(logs_dir: Path) -> Path:
    return logs_dir / "phase_3"


def phase3_activation_path(logs_dir: Path) -> Path:
    return phase3_dir(logs_dir) / "phase_3_activation.json"


def phase3_opening_agenda_path(logs_dir: Path) -> Path:
    return phase3_dir(logs_dir) / "phase_3_opening_research_agenda.md"


def load_phase3_activation(logs_dir: Path) -> dict[str, Any]:
    path = phase3_activation_path(logs_dir)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) and payload.get("schema_version") == PHASE3_SCHEMA_VERSION else {}


def compact_score(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "n": row.get("n"),
        "wins": row.get("wins"),
        "losses": row.get("losses"),
        "win_rate_pct": row.get("win_rate_pct"),
        "total_r": row.get("total_r"),
        "expectancy_r": row.get("expectancy_r"),
        "profit_factor": row.get("profit_factor"),
        "median_r": row.get("median_r"),
        "max_drawdown_r": row.get("max_drawdown_r"),
    }


def build_autopsy(snapshot: dict[str, Any]) -> dict[str, Any]:
    scorecard = snapshot.get("scorecard", {})
    overall = compact_score(scorecard.get("overall", {}))
    by_setup = {key: compact_score(value) for key, value in scorecard.get("by_setup", {}).items()}
    by_symbol = {key: compact_score(value) for key, value in scorecard.get("by_symbol", {}).items()}
    by_direction = {key: compact_score(value) for key, value in scorecard.get("by_direction", {}).items()}
    by_time_bucket = {key: compact_score(value) for key, value in scorecard.get("by_time_bucket", {}).items()}
    by_dte = {key: compact_score(value) for key, value in scorecard.get("by_dte", {}).items()}
    return {
        "source": snapshot.get("snapshot_artifacts", {}).get("snapshot_json", ""),
        "cohort_version": snapshot.get("cohort_version", COHORT_VERSION),
        "headline": overall,
        "strategy_observations": snapshot.get("strategy_observations"),
        "independent_opportunities": snapshot.get("independent_opportunities", {}),
        "dependence": snapshot.get("dependence", {}),
        "by_setup": by_setup,
        "by_symbol": by_symbol,
        "by_direction": by_direction,
        "by_time_bucket": by_time_bucket,
        "by_dte": by_dte,
        "primary_question": "Why did QQQ / Setup B Short appear positive while SPY long Setups A/C were strongly negative?",
        "interpretation": [
            "Setup B Short / QQQ / short is the only positive Cohort 1 pocket, but N=10 and dependence/same-period effects prevent validation.",
            "SPY long Setups A/C were materially negative and should be challenged before receiving more research capital.",
            "The symbol, direction, setup, time-period, and options-implementation effects are entangled; Phase 3 must separate them with controlled tests.",
            "Cohort 1 is useful for hypothesis generation, not live-capital authorization.",
        ],
        "insufficient_evidence_dimensions": [
            "market regime",
            "volatility regime",
            "trend strength",
            "delta",
            "spread/liquidity",
            "MAE/MFE",
            "stop placement",
            "target placement",
            "delayed-entry sensitivity",
            "delayed-exit sensitivity",
            "seasonality versus regime",
        ],
        "timing_limitations": snapshot.get("evidence_limitations", []),
    }


def opening_hypotheses(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "hypothesis_id": "P3-H001",
            "name": "QQQ Setup B Short Continuation May Contain a Repeatable Bearish Continuation Edge",
            "strategy_family": "VWAP + EMA Trend Continuation",
            "source": "Cohort 1 frozen setup/symbol/direction breakdown",
            "rationale": "Only Setup B Short / QQQ / short finished positive in Cohort 1.",
            "evidence_motivating_it": "Setup B Short N=10, total +1.7292R, expectancy +0.1729R, PF 1.6807.",
            "intended_symbols": ["QQQ"],
            "intended_directions": ["short"],
            "suspected_regime": "Bearish trend or intraday continuation; INSUFFICIENT EVIDENCE.",
            "parent_strategy_version": "Cohort 1 VWAP + EMA Setup B",
            "evidence_limitations": "Small N, concentrated in one symbol/direction/time period; not independent validation.",
            "research_priority": "HIGH",
            "expected_information_value": "HIGH",
            "proposed_first_test": "Quick-screen QQQ Setup B Short across prior comparable periods and full-year contexts without changing rules.",
            "current_stage": "HYPOTHESIS",
        },
        {
            "hypothesis_id": "P3-H002",
            "name": "SPY Long Setup A/C Weakness May Be Structural Rather Than Noise",
            "strategy_family": "VWAP + EMA Trend Continuation",
            "source": "Cohort 1 frozen negative SPY long evidence",
            "rationale": "SPY long observations dominated losses across Setup A and Setup C.",
            "evidence_motivating_it": "SPY N=20, total -5.1801R, expectancy -0.2590R; long N=20 same result.",
            "intended_symbols": ["SPY"],
            "intended_directions": ["long"],
            "suspected_regime": "Bullish continuation failure / chop vulnerability; INSUFFICIENT EVIDENCE.",
            "parent_strategy_version": "Cohort 1 VWAP + EMA Setups A/C",
            "evidence_limitations": "Setup A/C dependence groups share underlying opportunities; no hindsight relabeling allowed.",
            "research_priority": "HIGH",
            "expected_information_value": "HIGH",
            "proposed_first_test": "Autopsy losing SPY long cohorts by regime, time bucket, DTE, and entry/exit timing to decide whether to shelve or split.",
            "current_stage": "HYPOTHESIS",
        },
        {
            "hypothesis_id": "P3-H003",
            "name": "Cohort 1 Performance May Be a Symbol x Direction Interaction",
            "strategy_family": "Portfolio Research / Strategy Selection",
            "source": "Cohort 1 QQQ-short positive versus SPY-long negative split",
            "rationale": "The positive pocket and negative pocket are perfectly aligned with both symbol and direction.",
            "evidence_motivating_it": "QQQ short +1.7292R versus SPY long -5.1801R.",
            "intended_symbols": ["SPY", "QQQ"],
            "intended_directions": ["long", "short"],
            "suspected_regime": "Direction/symbol selection effect; INSUFFICIENT EVIDENCE.",
            "parent_strategy_version": "Cohort 1 aggregate VWAP + EMA",
            "evidence_limitations": "Cannot separate symbol, direction, setup, and collection-period effects from Cohort 1 alone.",
            "research_priority": "MEDIUM",
            "expected_information_value": "HIGH",
            "proposed_first_test": "Run controlled historical screens that hold setup constant while crossing symbol and direction.",
            "current_stage": "HYPOTHESIS",
        },
        {
            "hypothesis_id": "P3-H004",
            "name": "Time-of-Day May Explain Part of Cohort 1 Edge/Failure",
            "strategy_family": "Execution Timing / Intraday Structure",
            "source": "Cohort 1 time-bucket breakdown",
            "rationale": "Midday and late-day buckets were positive while opening-hour and late-morning were negative.",
            "evidence_motivating_it": "Midday +1.78R, late-day +1.9428R; late-morning -4.7758R.",
            "intended_symbols": ["SPY", "QQQ"],
            "intended_directions": ["long", "short"],
            "suspected_regime": "Intraday continuation quality varies by time bucket; INSUFFICIENT EVIDENCE.",
            "parent_strategy_version": "Cohort 1 timing analysis",
            "evidence_limitations": "Small sample and correlated with setup/symbol/direction.",
            "research_priority": "MEDIUM",
            "expected_information_value": "MEDIUM",
            "proposed_first_test": "Quick-screen existing setups by locked time bucket across historical periods.",
            "current_stage": "HYPOTHESIS",
        },
        {
            "hypothesis_id": "P3-H005",
            "name": "Opening Range Breakout Remains a Separate Prepared Research Family",
            "strategy_family": "Opening Range Breakout",
            "source": "Existing Strategy Vault / ORB shadow evidence lane",
            "rationale": "ORB may diversify away from VWAP + EMA continuation and has separate accumulated evidence.",
            "evidence_motivating_it": "Existing ORB shadow/forward observations exist but are not Cohort 1 official validation evidence.",
            "intended_symbols": ["SPY", "QQQ"],
            "intended_directions": ["long"],
            "suspected_regime": "Opening strength / momentum; INSUFFICIENT EVIDENCE for validation.",
            "parent_strategy_version": "ORB shadow research",
            "evidence_limitations": "Must remain separate from Cohort 1 and official VWAP evidence.",
            "research_priority": "MEDIUM",
            "expected_information_value": "MEDIUM",
            "proposed_first_test": "Define a quick-screen that uses existing ORB evidence without connecting ORB to live/paper execution.",
            "current_stage": "HYPOTHESIS",
        },
    ]


def opening_research_queue(hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {item["hypothesis_id"]: item for item in hypotheses}

    def item(hypothesis_id: str, why: str) -> dict[str, str]:
        hypothesis = by_id[hypothesis_id]
        return {
            "hypothesis_id": hypothesis_id,
            "name": hypothesis["name"],
            "stage": hypothesis["current_stage"],
            "priority": hypothesis["research_priority"],
            "why": why,
        }

    return {
        "status": "ACTIVE",
        "now_researching": [
            item("P3-H001", "Highest positive Cohort 1 pocket and fastest route to deciding whether an edge candidate exists."),
            item("P3-H002", "Highest loss-driver autopsy; can cheaply prevent wasting Phase 3 runway on weak SPY long variants."),
        ],
        "up_next": [
            item("P3-H003", "Separates symbol and direction effects after the two highest-priority autopsies."),
            item("P3-H004", "Tests whether timing is an independent explanatory factor or merely correlated noise."),
        ],
        "waiting_for_evidence": [
            item("P3-H005", "Diversifying prepared family, but should not crowd out Cohort 1 autopsy in the first research batch."),
        ],
        "on_hold": [
            {
                "name": "Broad parameter optimization",
                "stage": "ON HOLD",
                "priority": "LOW",
                "why": "Optimization before underlying-behavior proof risks curve fitting.",
            },
            {
                "name": "Execution & Latency Auditor activation",
                "stage": "ON HOLD",
                "priority": "LOW",
                "why": "Timing is important but activation was not approved in this directive.",
            },
        ],
    }


def proposed_experiments() -> list[dict[str, Any]]:
    return [
        {
            "experiment_id": "P3-E001",
            "name": "QQQ Setup B Short Historical Quick Screen",
            "linked_hypotheses": ["P3-H001", "P3-H003"],
            "purpose": "Determine whether QQQ short continuation appears outside Cohort 1's collection window.",
            "first_test": "Same rules, historical comparable periods, full-year context, no parameter optimization.",
            "stage": "PROPOSED",
            "production_isolation": "Offline research only; no production critical-path work.",
        },
        {
            "experiment_id": "P3-E002",
            "name": "SPY Long Setup A/C Failure Autopsy",
            "linked_hypotheses": ["P3-H002", "P3-H003", "P3-H004"],
            "purpose": "Decide whether SPY long A/C should be shelved, split, or subjected to deeper discovery.",
            "first_test": "Frozen Cohort 1 slicing plus historical baseline by setup, time bucket, DTE, and regime where available.",
            "stage": "PROPOSED",
            "production_isolation": "Offline research only; no production critical-path work.",
        },
        {
            "experiment_id": "P3-E003",
            "name": "ORB Evidence Quick-Screen Design",
            "linked_hypotheses": ["P3-H005"],
            "purpose": "Define the smallest read-only ORB evidence review that can compete for Phase 3 research capital.",
            "first_test": "Inventory existing ORB shadow/forward evidence and define locked pre-test metrics before analysis.",
            "stage": "PROPOSED",
            "production_isolation": "Read-only evidence review; no paper/live connection.",
        },
    ]


def portfolio_gaps() -> list[dict[str, str]]:
    return [
        {
            "gap": "No validated long-side playbook",
            "why_it_matters": "Cohort 1 long observations were materially negative, leaving bullish trend participation unproven.",
        },
        {
            "gap": "No validated range/chop playbook",
            "why_it_matters": "Current evidence focuses on continuation/failure candidates; low-volatility range behavior remains uncovered.",
        },
        {
            "gap": "No governed regime taxonomy tied to edge eligibility",
            "why_it_matters": "Phase 3 needs regime labels to distinguish seasonality, regime, strategy failure, and small-sample noise.",
        },
        {
            "gap": "No persisted independent-opportunity identity",
            "why_it_matters": "Independent opportunity count is currently derived/effective, which limits statistical confidence automation.",
        },
    ]


def kpi_baseline() -> dict[str, int]:
    return {
        "ideas_tested": 0,
        "edge_candidates": 0,
        "forward_candidates": 0,
        "validated_edges": 0,
        "hypotheses_screened": 0,
        "hypotheses_shelved": 0,
        "research_decisions_this_week": 0,
    }


def markdown_agenda(payload: dict[str, Any]) -> str:
    autopsy = payload["cohort_1_autopsy"]
    lines = [
        "# Project Gwala Phase 3 Opening Research Agenda",
        "",
        f"Activated: {payload['activated_at']}",
        "",
        "## Status",
        "",
        "- Phase 2: COMPLETE",
        "- Cohort 1: FROZEN",
        "- Phase 3: ACTIVE",
        "- Research Factory: ACTIVE",
        "- Edge Discovery: ACTIVE",
        "- Broker / Real Money: DISABLED",
        "",
        "## Cohort 1 Autopsy",
        "",
        f"- Strategy observations: {autopsy['strategy_observations']}",
        f"- Independent opportunities: {autopsy['independent_opportunities'].get('value')} ({autopsy['independent_opportunities'].get('provenance')})",
        f"- Total R: {autopsy['headline'].get('total_r')}R",
        f"- Expectancy: {autopsy['headline'].get('expectancy_r')}R",
        f"- Profit factor: {autopsy['headline'].get('profit_factor')}",
        "",
        "## Opening Hypotheses",
    ]
    for hypothesis in payload["hypothesis_registry"]["items"]:
        lines.extend(
            [
                "",
                f"### {hypothesis['hypothesis_id']} - {hypothesis['name']}",
                f"- Priority: {hypothesis['research_priority']}",
                f"- Stage: {hypothesis['current_stage']}",
                f"- Rationale: {hypothesis['rationale']}",
                f"- First test: {hypothesis['proposed_first_test']}",
            ]
        )
    lines.extend(["", "## Research Queue"])
    for bucket in ["now_researching", "up_next", "waiting_for_evidence", "on_hold"]:
        lines.append("")
        lines.append(f"### {bucket.replace('_', ' ').title()}")
        for item in payload["research_queue"][bucket]:
            lines.append(f"- {item['name']}: {item['why']}")
    lines.extend(
        [
            "",
            "## Production Boundary",
            "",
            "Phase 3 research is offline/read-only until separately approved. It must not delay M30 entry decisions, M5 legitimate open-position management, candidate lifecycle, or critical market data.",
        ]
    )
    return "\n".join(lines) + "\n"


def activate_phase3(
    *,
    logs_dir: Path,
    production_commit: str,
    activated_at: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    path = phase3_activation_path(logs_dir)
    if path.exists() and not force:
        raise FileExistsError(f"Phase 3 activation already exists: {path}")
    snapshot = load_cohort_1_freeze(logs_dir)
    if snapshot.get("status") != "FROZEN":
        raise ValueError("Cohort 1 must be frozen before Phase 3 activation.")
    hypotheses = opening_hypotheses(snapshot)
    payload = {
        "schema_version": PHASE3_SCHEMA_VERSION,
        "activated_at": activated_at or datetime.now().isoformat(),
        "production_commit": production_commit,
        "phase_2": "COMPLETE",
        "cohort_1": {
            "status": "FROZEN",
            "cohort_version": snapshot.get("cohort_version", COHORT_VERSION),
            "snapshot_path": snapshot.get("snapshot_artifacts", {}).get("snapshot_json", ""),
            "strategy_observations": snapshot.get("strategy_observations"),
            "independent_opportunities": snapshot.get("independent_opportunities", {}),
        },
        "phase_3": "ACTIVE",
        "research_factory": "ACTIVE",
        "edge_discovery": "ACTIVE",
        "broker_real_money": "DISABLED",
        "capital_boundary": "Tiny Live and real-money trading remain disabled until separate explicit approval.",
        "cohort_boundary": "Phase 3 may read cohort_1_v1 but may not rewrite, relabel, amend, or optimize it retroactively.",
        "production_boundary": "Research must remain off the decision-critical production lane.",
        "cohort_1_autopsy": build_autopsy(snapshot),
        "hypothesis_registry": {
            "status": "ACTIVE",
            "count": len(hypotheses),
            "items": hypotheses,
        },
        "research_queue": opening_research_queue(hypotheses),
        "proposed_experiments": proposed_experiments(),
        "portfolio_gaps": portfolio_gaps(),
        "kpi_baseline": kpi_baseline(),
        "guardrail": "No broad historical mining launched by activation. Investment Committee must review the opening agenda first.",
    }
    phase3_dir(logs_dir).mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    phase3_opening_agenda_path(logs_dir).write_text(markdown_agenda(payload), encoding="utf-8")
    return payload

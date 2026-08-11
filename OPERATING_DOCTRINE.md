# Project Gwala Operating Doctrine

Last updated: 2026-08-07

This file is the authoritative operating doctrine for Project Gwala.

## Mission

Build a quantitative trading firm that reaches sustainable profitability as
quickly as reasonably possible.

Primary objective:

```text
Discover the firm's first commercially viable trading edge.
```

Default operating mode:

```text
EXECUTE
```

## Capital Philosophy

The firm optimizes for maximum long-term compounded capital growth while
maintaining an extremely low probability of ruin.

Investment Committee priorities:

1. Capital Preservation
2. Risk-Adjusted Growth
3. Commercial Profitability
4. Return Maximization

Monthly target:

```text
20% average monthly return over time
```

Returns above target should come from superior opportunity selection and
capital allocation, not increased per-trade risk.

The firm never becomes more aggressive because it is behind a monthly target.
Aggression is earned by stronger evidence.

## Recommendation Framework

Every Executive Report and material decision must conclude with exactly one:

- CONTINUE
- INVESTIGATE
- BUILD
- REALLOCATE

Use BUILD only when evidence demonstrates that engineering has a higher
expected return than continued evidence collection.

Use REALLOCATE only when another strategy has earned additional research
capital.

If no new action is earned, state:

```text
No new action earned today. Continue execution.
```

## Research Runway Doctrine

Every funded strategy must define:

- Promotion Criteria
- Continue Criteria
- Reduction Criteria
- Retirement Criteria
- Research Runway

Research Runway is the maximum amount of trading sessions, research capital,
and engineering attention that may be invested before a forced Investment
Committee decision.

At runway exhaustion, the committee must choose exactly one:

- PROMOTE
- CONTINUE with written justification
- REDUCE
- RETIRE

The default is not indefinite evidence collection.

## Promotion Rules

A strategy may advance only when evidence satisfies the approved trigger for
its current lifecycle stage.

General promotion path:

```text
Research -> Shadow -> Primary Research -> Manual Paper Trading -> Live Capital
```

Promotion requires decision-quality evidence, clean operational timing, clear
audit trail, and no unresolved safety/accounting defect.

## Continue Rules

Continue only when:

- runway remains,
- no reduction or retirement trigger has crossed,
- evidence velocity is adequate,
- the strategy remains competitive on expected return on research time,
- no higher-ROI lane has earned reallocation.

## Reduction Rules

Reduce research allocation when evidence weakens but does not yet justify
retirement, or when another funded lane has a higher expected speed to
discovering a profitable edge.

## Retirement Rules

Retire or stop funding when measurable failure criteria are crossed, when
runway is exhausted without adequate justification to continue, or when
commercial viability becomes unlikely relative to other available research
lanes.

## Evidence Quality Rules

Evidence must be separated by source and meaning:

- historical backtests,
- shadow evidence,
- forward observations,
- Manual Paper-Watch evidence,
- official paper trades,
- live capital results.

Preview candidates do not count as completed official evidence.

Operational interruptions must be recorded as evidence-confidence metadata
instead of being ignored.

Engineering Trigger confidence levels:

- LOW: single observation.
- MEDIUM: observed more than once, but alternatives remain plausible.
- HIGH: repeated observations across multiple sessions with same root cause.
- CONFIRMED: root cause identified and business impact proven.

## Strategic Drift Rules

Do not optimize for engineering, elegance, architecture completion, or proving
one strategy correct.

Optimize for commercial progress:

```text
Does this materially increase the probability that Gwala becomes profitable sooner?
```

Casual discussion does not become doctrine unless recorded in the authoritative
memory files or explicitly approved by the Investment Committee.

## Continuity Rule

When a material decision changes mission, roadmap, strategy lifecycle, research
allocation, capital allocation, risk policy, commercialization, company
doctrine, or critical architecture, it must be either:

1. written into the appropriate authoritative company-memory file, or
2. explicitly labeled DISCUSSION ONLY / NOT ADOPTED.

## Conflict Rule

If a future instruction conflicts with an authoritative decision, surface:

- existing rule,
- proposed new rule,
- conflict,
- evidence supporting change,
- required Investment Committee decision.

Do not silently overwrite authority.

## Design Principle: Loops, Not Just Scripts

Gwala should behave like an operating firm, not a folder of disconnected
scripts.

The system should create loops:

- collect evidence,
- evaluate triggers,
- make capital-allocation decisions,
- execute the next highest-ROI action,
- record decisions,
- preserve continuity.

The goal is not more automation for its own sake. The goal is faster,
higher-confidence movement toward a commercially viable trading edge.

## Non-Negotiable Safety Rules

- No live broker orders without explicit future approval.
- No real-money execution during Phase 2.
- No martingale logic.
- No averaging down losers.
- No revenge-trade behavior.
- No overleverage.
- No stop-loss removal.
- No loosening rules merely to force trade count.
- No contamination between strategy evidence ledgers.


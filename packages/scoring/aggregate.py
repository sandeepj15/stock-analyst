"""Score aggregation: renormalization + confidence (SPEC.md sections 18, 20, 22, 86).

This module is deliberately decoupled from the database and from any
particular component's internal scoring logic: it takes a plain list of
already-computed `ComponentResult`s and produces the headline score,
confidence, and the per-component explainability breakdown. That
decoupling is what makes the required test matrix (SPEC.md section 86:
"all components 100", "all 0", "some missing", "stale data", "one input
changes") directly testable with synthetic `ComponentResult` lists - no
DB, no OHLCV fixtures needed.

## Missing-component renormalization formula

```
available_weight = sum(weight for component in components if component.available)
score = sum(component.score * component.weight for component in components if component.available)
        / available_weight
```

i.e. a weighted average over only the components that produced a real
number, divided by the sum of *their* weights (not the full 1.0, and
never treating a missing component as 0 or as a neutral 50 - SPEC.md
section 86/22). If `available_weight == 0` (every component missing),
`score` is `None` - there is nothing to report, not a fabricated 0 or 50.

Per-component `weight_used` is the renormalized weight
(`component.weight / available_weight`, 0 if unavailable) and
`contribution = component.score * weight_used`. By construction,
`sum(contribution for all components) == score`.

## Confidence formula

```
weight_coverage_pct = available_weight / total_weight * 100
freshness_avg = mean(component.freshness for component in components if component.available)
confidence = clamp(0.7 * weight_coverage_pct + 0.3 * freshness_avg, 0, 100)
```

`freshness` (0-100 per component) captures staleness of that component's
*underlying inputs* (SPEC.md section 22's "financial data is stale"
example) independently of the component's own score - a stale-but-still-
computed fundamentals component lowers confidence via the freshness term
even though it still contributes its score normally to the headline
number. Components with no staleness dimension (technical, momentum,
risk, sector relative strength, market regime - all derived from the
latest available bar) report `freshness=100.0`. If no component is
available at all, `confidence = 0.0`.

Score and confidence are always returned as two independent numbers -
never collapsed into one (SPEC.md section 22: "Score = 85, Confidence =
51" must be representable, and is: a very stale fundamentals component
can coexist with a high headline score).
"""
from __future__ import annotations

from dataclasses import dataclass, field

CONFIDENCE_WEIGHT_COVERAGE_WEIGHT = 0.7
CONFIDENCE_FRESHNESS_WEIGHT = 0.3


@dataclass(frozen=True)
class ComponentResult:
    """One component's computed (or not) result, before renormalization."""

    name: str
    weight: float
    score: float | None
    available: bool
    reason: str | None
    freshness: float  # 0-100; meaningless (but present) when not available
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AggregatedComponent:
    name: str
    weight: float
    weight_used: float
    score: float | None
    contribution: float
    available: bool
    reason: str | None
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class AggregateResult:
    score: float | None
    confidence: float
    components: tuple[AggregatedComponent, ...]


def aggregate_components(components: list[ComponentResult]) -> AggregateResult:
    total_weight = sum(c.weight for c in components)
    available = [c for c in components if c.available and c.score is not None]
    available_weight = sum(c.weight for c in available)

    score: float | None = None
    if available_weight > 0:
        # `available` is already filtered to `c.score is not None`, but
        # mypy can't carry that narrowing through the list comprehension -
        # the `if c.score is not None else 0.0` branch is unreachable in
        # practice, just satisfies the type checker.
        score = sum((c.score if c.score is not None else 0.0) * c.weight for c in available) / available_weight

    weight_coverage_pct = (available_weight / total_weight * 100.0) if total_weight > 0 else 0.0
    freshness_avg = (sum(c.freshness for c in available) / len(available)) if available else 0.0
    confidence = max(
        0.0,
        min(100.0, CONFIDENCE_WEIGHT_COVERAGE_WEIGHT * weight_coverage_pct + CONFIDENCE_FRESHNESS_WEIGHT * freshness_avg),
    )

    aggregated: list[AggregatedComponent] = []
    for c in components:
        is_counted = c.available and c.score is not None and available_weight > 0
        weight_used = (c.weight / available_weight) if is_counted else 0.0
        contribution = (c.score * weight_used) if is_counted and c.score is not None else 0.0
        aggregated.append(
            AggregatedComponent(
                name=c.name,
                weight=c.weight,
                weight_used=weight_used,
                score=c.score,
                contribution=contribution,
                available=c.available,
                reason=c.reason,
                evidence=c.evidence_ids,
            )
        )

    return AggregateResult(score=score, confidence=confidence, components=tuple(aggregated))

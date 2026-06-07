"""
Verifier adapter -- Stage 5 of the loop (VERIFY).

After an action, re-check the signal's metric to decide whether the system
actually recovered. Like the detector, the metric query is isolated behind a
seam so the recovery logic is testable without Prometheus.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.models import Incident, Verification

# Given an incident, return the current value of its signal's metric.
MetricFn = Callable[[Incident], float]


class StaticVerifier:
    """Returns a fixed verification. For tests/demos."""

    def __init__(self, verification: Verification) -> None:
        self._v = verification

    def verify(self, incident: Incident) -> Verification:
        return self._v


class ThresholdVerifier:
    """
    Recovered if the metric has dropped back to (or below) the signal's
    threshold after the action. `metric_fn` fetches the current value.
    """

    def __init__(self, metric_fn: MetricFn) -> None:
        self._metric = metric_fn

    def verify(self, incident: Incident) -> Verification:
        before = incident.signal.value
        after = self._metric(incident)
        recovered = after <= incident.signal.threshold
        return Verification(
            recovered=recovered,
            metric_before=before,
            metric_after=after,
            detail=f"metric {'recovered' if recovered else 'still elevated'} at {after:.3f}",
        )

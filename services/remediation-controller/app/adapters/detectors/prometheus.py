"""
Detector adapters -- Stage 1 of the loop (DETECT).

Detection is deterministic and statistical -- NEVER an LLM. A detector queries a
metrics source and emits a Signal for each metric that has crossed a threshold.

Two implementations:
  - PrometheusDetector: queries Prometheus over HTTP. The HTTP call is isolated
    behind a tiny `query_fn` seam so the detection LOGIC (threshold comparison,
    severity assignment) is testable without a live Prometheus.
  - StaticDetector: returns pre-set signals, for tests and local demos.

The threshold logic here is intentionally simple (value vs threshold). A
production detector would use the burn-rate / EWMA / z-score approaches already
defined in the platform's PrometheusRules; the point of this adapter is the port
boundary and severity mapping, not novel statistics.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.models import Severity, Signal


class StaticDetector:
    """Returns a fixed list of signals. For tests and local demos."""

    def __init__(self, signals: list[Signal]) -> None:
        self._signals = signals

    def detect(self) -> list[Signal]:
        return list(self._signals)


# A query function takes a PromQL string and returns a float (the scalar result).
# Injecting it keeps the network out of the detection logic.
QueryFn = Callable[[str], float]


class PrometheusDetector:
    """
    Detects signals by evaluating a set of PromQL rules against Prometheus.

    Each rule is (name, promql, threshold, source). When the query result
    exceeds the threshold, a Signal is emitted. Severity scales with how far
    past the threshold the value is.
    """

    def __init__(
        self,
        rules: list[tuple[str, str, float, str]],
        query_fn: QueryFn,
    ) -> None:
        self._rules = rules
        self._query = query_fn

    @staticmethod
    def _severity(value: float, threshold: float) -> Severity:
        if threshold <= 0:
            return Severity.WARNING
        ratio = value / threshold
        if ratio >= 3.0:
            return Severity.CRITICAL
        if ratio >= 1.0:
            return Severity.WARNING
        return Severity.INFO

    def detect(self) -> list[Signal]:
        signals: list[Signal] = []
        for metric, promql, threshold, source in self._rules:
            try:
                value = self._query(promql)
            except Exception:
                # A failed scrape is not a remediation signal; skip it. (Detector
                # health itself would be monitored separately.)
                continue
            if value > threshold:
                signals.append(
                    Signal(
                        source=source,
                        metric=metric,
                        value=value,
                        threshold=threshold,
                        severity=self._severity(value, threshold),
                        description=f"{metric} at {value:.3f} exceeded {threshold:.3f}",
                    )
                )
        return signals

"""
MockDiagnoser -- a deterministic, rule-based Diagnoser.

This implements the Diagnoser port WITHOUT any LLM. It exists so the whole loop
can be developed, tested, and demoed with zero API cost and perfect
reproducibility. It also serves as the reference for what a "good" diagnosis
looks like, and as a safe fallback if a real LLM is unavailable.

DESIGN -- hybrid reasoning (fault type + severity):
    The action is driven primarily by WHAT failed (the signal's metric and
    description), and the severity MODULATES the confidence. This mirrors how an
    operator actually reasons: the same severity can demand different actions
    depending on the kind of failure.

      - A data-dependency failure (database unreachable) -> ESCALATE. Restarting
        a pod cannot fix a dead database; the safe move is a human. The actual
        data recovery happens later in the always-on replay stage.
      - A pod-level error (high error ratio, crash-looping) -> RESTART_POD.
      - A saturation/overload signal (latency + resource pressure) -> SCALE_UP.
      - Anything unrecognized -> ESCALATE (fail-safe: never guess an action).
      - A benign/info signal -> NO_OP.

Crucially, the mock can ONLY return actions from the allowlist (ActionType) --
exactly the same constraint the real LLM diagnoser operates under. The mock and
the LLM are interchangeable behind the Diagnoser port; the LLM just brings
nuance the rules can't capture, never new powers.
"""

from __future__ import annotations

from app.core.models import ActionType, Diagnosis, Severity, Signal


# Keywords we look for in a signal to classify the FAULT TYPE. Kept simple and
# explicit on purpose: this is a deterministic baseline, not the clever part.
_DATABASE_HINTS = ("database", "db", "sql", "mongo", "mysql", "connection refused", "unreachable")
_SATURATION_HINTS = ("latency", "saturation", "overload", "cpu", "memory", "throttl", "slow")
_POD_ERROR_HINTS = ("error ratio", "5xx", "crash", "restart", "degraded", "error rate")


def _text(signal: Signal) -> str:
    """All the searchable text of a signal, lowercased."""
    return f"{signal.metric} {signal.description}".lower()


def _confidence_for(severity: Severity, base: float) -> float:
    """
    Severity modulates confidence. A clear, severe signal is more actionable;
    a mild one leaves more room for doubt (which the policy gate may turn into
    'requires approval'). Clamped to [0, 1].
    """
    bump = {Severity.CRITICAL: 0.10, Severity.WARNING: 0.0, Severity.INFO: -0.20}[severity]
    return max(0.0, min(1.0, base + bump))


class MockDiagnoser:
    """Deterministic Diagnoser. Satisfies the Diagnoser port structurally."""

    def diagnose(self, signal: Signal) -> Diagnosis:
        text = _text(signal)
        target = signal.source

        # Benign / informational -> do nothing.
        if signal.severity is Severity.INFO and not any(
            h in text for h in _DATABASE_HINTS + _POD_ERROR_HINTS
        ):
            return Diagnosis(
                proposed_action=ActionType.NO_OP,
                confidence=_confidence_for(signal.severity, 0.80),
                rationale="informational signal with no actionable fault pattern",
                target=target,
            )

        # Data-dependency failure -> ESCALATE (a restart can't fix dead data;
        # the replay stage recovers data later, after a human restores the DB).
        if any(h in text for h in _DATABASE_HINTS):
            return Diagnosis(
                proposed_action=ActionType.ESCALATE,
                confidence=_confidence_for(signal.severity, 0.85),
                rationale=(
                    "data-dependency failure detected; automated pod actions cannot "
                    "recover a database, so defer to a human and let the replay stage "
                    "recover lost data after restoration"
                ),
                target=target,
            )

        # Saturation / overload -> SCALE_UP.
        if any(h in text for h in _SATURATION_HINTS):
            return Diagnosis(
                proposed_action=ActionType.SCALE_UP,
                confidence=_confidence_for(signal.severity, 0.75),
                rationale="resource saturation pattern; adding replicas should relieve load",
                target=target,
            )

        # Pod-level errors -> RESTART_POD.
        if any(h in text for h in _POD_ERROR_HINTS):
            return Diagnosis(
                proposed_action=ActionType.RESTART_POD,
                confidence=_confidence_for(signal.severity, 0.80),
                rationale="pod-level error pattern; a restart commonly clears the fault",
                target=target,
            )

        # Unrecognized -> ESCALATE (fail-safe: never guess an action).
        return Diagnosis(
            proposed_action=ActionType.ESCALATE,
            confidence=_confidence_for(signal.severity, 0.50),
            rationale="unrecognized fault pattern; escalating rather than guessing",
            target=target,
        )
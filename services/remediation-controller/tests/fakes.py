"""
Test doubles (fakes) for the loop's ports.

These are deliberately tiny and deterministic. They let us test the engine's
orchestration logic in complete isolation from real infrastructure -- no
Kubernetes, no Prometheus, no LLM, no Redpanda, no Slack, no database. Each
fake is configurable so a test can drive the engine down any branch.
"""

from __future__ import annotations

from app.core.models import (
    ActionResult,
    ActionType,
    Diagnosis,
    Incident,
    PolicyVerdict,
    PostMortem,
    ReplayResult,
    Severity,
    Signal,
    Verification,
)


class FakeDetector:
    """Emits a fixed list of signals (whatever the test wants to inject)."""

    def __init__(self, signals: list[Signal]) -> None:
        self._signals = signals

    def detect(self) -> list[Signal]:
        return list(self._signals)


class FakeDiagnoser:
    """Always proposes the diagnosis it was constructed with."""

    def __init__(self, diagnosis: Diagnosis) -> None:
        self._diagnosis = diagnosis

    def diagnose(self, signal: Signal) -> Diagnosis:
        return self._diagnosis


class FakePolicyGate:
    """Returns a fixed verdict."""

    def __init__(self, verdict: PolicyVerdict) -> None:
        self._verdict = verdict

    def evaluate(self, incident: Incident) -> PolicyVerdict:
        return self._verdict


class FakeActuator:
    """
    Records whether it was called and with what dry_run flag, and returns a
    configurable result. Lets us assert the engine respected dry-run, etc.
    """

    def __init__(self, result: ActionResult | None = None) -> None:
        self._result = result
        self.called = False
        self.called_dry_run: bool | None = None

    def execute(self, incident: Incident, dry_run: bool) -> ActionResult:
        self.called = True
        self.called_dry_run = dry_run
        if self._result is not None:
            return self._result
        action = incident.diagnosis.proposed_action
        target = incident.diagnosis.target or incident.signal.source
        return ActionResult(
            action=action,
            target=target,
            executed=not dry_run,
            dry_run=dry_run,
            detail="fake execution",
        )


class FakeVerifier:
    """Returns a fixed verification."""

    def __init__(self, verification: Verification) -> None:
        self._verification = verification

    def verify(self, incident: Incident) -> Verification:
        return self._verification


class FakeReplayer:
    """Records whether it ran and returns a configurable replay result."""

    def __init__(self, result: ReplayResult | None = None) -> None:
        self._result = result if result is not None else ReplayResult(0, 0, 0)
        self.called = False

    def replay(self, incident: Incident) -> ReplayResult:
        self.called = True
        return self._result


class RecordingEscalator:
    """Records every escalation so tests can assert on them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (incident_id, reason)

    def escalate(self, incident: Incident, reason: str) -> None:
        self.calls.append((incident.id, reason))


class FakePostMortemWriter:
    """
    Generates a trivial post-mortem from the incident, and records that it ran.
    Mirrors what the real LLM-backed writer will do, deterministically.
    """

    def __init__(self) -> None:
        self.called = False

    def write(self, incident: Incident) -> PostMortem:
        self.called = True
        escalated = incident.outcome.value == "escalated"
        if incident.replay_result is not None:
            r = incident.replay_result
            data_recovery = f"{r.succeeded}/{r.attempted} recovered"
        else:
            data_recovery = "no replay performed"
        return PostMortem(
            summary=f"{incident.signal.source}: {incident.signal.description}",
            timeline=tuple(e.message for e in incident.audit_trail),
            data_recovery=data_recovery,
            escalated=escalated,
        )


class InMemoryIncidentStore:
    """
    Stores incidents in a dict. Stands in for the Redis (active) + MongoDB
    (history) split that production will use; the core only sees this interface.
    """

    def __init__(self) -> None:
        self.saved: dict[str, Incident] = {}

    def save(self, incident: Incident) -> None:
        self.saved[incident.id] = incident

    def get(self, incident_id: str) -> Incident | None:
        return self.saved.get(incident_id)


# -- Convenience builders -----------------------------------------------------

def make_signal(
    severity: Severity = Severity.CRITICAL,
    source: str = "events-api",
    description: str = "error ratio above threshold",
) -> Signal:
    return Signal(
        source=source,
        metric="http_error_ratio",
        value=0.42,
        threshold=0.05,
        severity=severity,
        description=description,
    )


def make_diagnosis(
    action: ActionType = ActionType.RESTART_POD,
    confidence: float = 0.9,
    target: str = "events-api",
) -> Diagnosis:
    return Diagnosis(
        proposed_action=action,
        confidence=confidence,
        rationale="fake rationale",
        target=target,
    )
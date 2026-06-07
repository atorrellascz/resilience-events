"""
Integration tests -- the whole loop wired with REAL adapters (not engine fakes).

These exercise the composition root and the concrete adapters together:
MockDiagnoser + RiskBasedPolicyGate + KubernetesActuator(FakeOps) +
verifier + Redpanda replayer + template post-mortem + in-memory store.

This is the proof that the pieces fit: the same scenarios from test_scenarios.py,
but driven through the actual adapters rather than hand-fed fakes.
"""

from __future__ import annotations

from app.adapters.actuators.kubernetes import FakeKubernetesOps, KubernetesActuator
from app.adapters.detectors.prometheus import StaticDetector
from app.adapters.diagnosers.mock import MockDiagnoser
from app.adapters.policy.gate import PolicyConfig, RiskBasedPolicyGate, RiskLevel
from app.adapters.postmortem.writer import TemplatePostMortemWriter
from app.adapters.replayers.redpanda import RedpandaReplayer
from app.adapters.stores.memory import InMemoryIncidentStore
from app.adapters.verifiers.prometheus import StaticVerifier
from app.core.engine import EngineConfig, RemediationEngine
from app.core.models import Outcome, Severity, Signal, Verification
from app.wiring import build_default_engine


def _pod_signal():
    return Signal("events-api", "http_error_ratio", 0.30, 0.05, Severity.WARNING,
                  "elevated 5xx error ratio")


def _db_signal():
    return Signal("events-api", "db_ping", 1.0, 0.0, Severity.CRITICAL,
                  "SQL Server unreachable, connection refused")


# -----------------------------------------------------------------------------
# Default wiring is safe: dry-run, nothing executed
# -----------------------------------------------------------------------------

def test_default_engine_is_dry_run_safe():
    engine = build_default_engine([_pod_signal()])
    [incident] = engine.run_once()
    # restart_pod is LOW risk + high mock confidence -> approved, but dry-run
    # means it's simulated, not executed.
    assert incident.action_result is not None
    assert incident.action_result.executed is False
    assert incident.outcome is Outcome.NO_ACTION


# -----------------------------------------------------------------------------
# SCENARIO A -- stuck pod, autonomy enabled, real adapters end to end
# -----------------------------------------------------------------------------

def test_integration_stuck_pod_auto_remediates():
    ops = FakeKubernetesOps()
    store = InMemoryIncidentStore()
    engine = RemediationEngine(
        detector=StaticDetector([_pod_signal()]),
        diagnoser=MockDiagnoser(),                 # -> restart_pod (LOW risk)
        policy_gate=RiskBasedPolicyGate(),         # default ceiling LOW -> approves restart
        actuator=KubernetesActuator(ops),
        verifier=StaticVerifier(Verification(True, 0.30, 0.01, "recovered")),
        replayer=RedpandaReplayer(
            fetch_fn=lambda inc: list(range(8)),   # 8 lost records
            reprocess_fn=lambda rec: True,         # all replay fine
            source="redpanda:events.wal",
        ),
        escalator=_RecordingEscalator(),
        postmortem_writer=TemplatePostMortemWriter(),
        store=store,
        config=EngineConfig(dry_run=False),        # autonomy ON
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.RESOLVED
    assert ops.calls == ["delete_pod:events-api"]          # really "acted"
    assert incident.replay_result.succeeded == 8
    assert incident.postmortem is not None
    assert store.get(incident.id) is incident


# -----------------------------------------------------------------------------
# SCENARIO B -- database down: mock diagnoses ESCALATE, gate routes to human,
# nothing is executed against the data.
# -----------------------------------------------------------------------------

def test_integration_database_down_escalates_without_acting():
    ops = FakeKubernetesOps()
    esc = _RecordingEscalator()
    engine = RemediationEngine(
        detector=StaticDetector([_db_signal()]),
        diagnoser=MockDiagnoser(),                 # db hint -> ESCALATE
        policy_gate=RiskBasedPolicyGate(),
        actuator=KubernetesActuator(ops),
        verifier=StaticVerifier(Verification(False, 1.0, 1.0)),
        replayer=RedpandaReplayer(lambda i: [], lambda r: True),
        escalator=esc,
        postmortem_writer=TemplatePostMortemWriter(),
        store=InMemoryIncidentStore(),
        config=EngineConfig(dry_run=False),
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.ESCALATED
    assert ops.calls == []                          # NEVER acted on the data
    assert len(esc.calls) == 1
    assert incident.postmortem.escalated is True


# -----------------------------------------------------------------------------
# Risk ceiling in action: scale_up needs approval at default ceiling
# -----------------------------------------------------------------------------

def test_integration_saturation_requires_approval_at_default_ceiling():
    sat = Signal("events-api", "p99_latency", 0.9, 0.3, Severity.WARNING,
                 "high latency under CPU saturation")
    ops = FakeKubernetesOps()
    esc = _RecordingEscalator()
    engine = RemediationEngine(
        detector=StaticDetector([sat]),
        diagnoser=MockDiagnoser(),                 # saturation -> scale_up (MEDIUM)
        policy_gate=RiskBasedPolicyGate(),         # ceiling LOW -> requires approval
        actuator=KubernetesActuator(ops),
        verifier=StaticVerifier(Verification(True, 0.9, 0.1)),
        replayer=RedpandaReplayer(lambda i: [], lambda r: True),
        escalator=esc,
        postmortem_writer=TemplatePostMortemWriter(),
        store=InMemoryIncidentStore(),
        config=EngineConfig(dry_run=False),
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.ESCALATED   # requires approval -> escalated
    assert ops.calls == []                          # not executed without sign-off


class _RecordingEscalator:
    def __init__(self) -> None:
        self.calls = []

    def escalate(self, incident, reason) -> None:
        self.calls.append((incident.id, reason))

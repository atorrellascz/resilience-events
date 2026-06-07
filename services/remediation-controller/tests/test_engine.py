"""
Unit tests for the RemediationEngine -- orchestration logic.

These verify the engine routes an incident down the correct branch given each
stage's output, and enforces the safety rules (fail-safe escalation, dry-run by
default, never act without an APPROVED verdict, always write a post-mortem,
always persist). No real infrastructure is involved.

Run: PYTHONPATH=. pytest -q
"""

from __future__ import annotations

from app.core.engine import EngineConfig, RemediationEngine
from app.core.models import (
    ActionResult,
    ActionType,
    Decision,
    Outcome,
    PolicyVerdict,
    ReplayResult,
    Verification,
)
from tests.fakes import (
    FakeActuator,
    FakeDetector,
    FakeDiagnoser,
    FakePolicyGate,
    FakePostMortemWriter,
    FakeReplayer,
    FakeVerifier,
    InMemoryIncidentStore,
    RecordingEscalator,
    make_diagnosis,
    make_signal,
)


def _build(
    *,
    diagnosis,
    verdict=None,
    actuator=None,
    verification=None,
    replay=None,
    dry_run=True,
):
    """Assemble an engine wired with the given fakes; returns (engine, parts)."""
    escalator = RecordingEscalator()
    pm = FakePostMortemWriter()
    store = InMemoryIncidentStore()
    replayer = FakeReplayer(replay if replay is not None else ReplayResult(0, 0, 0))
    engine = RemediationEngine(
        detector=FakeDetector([make_signal()]),
        diagnoser=FakeDiagnoser(diagnosis),
        policy_gate=FakePolicyGate(verdict or PolicyVerdict(Decision.APPROVED, "ok")),
        actuator=actuator or FakeActuator(),
        verifier=FakeVerifier(verification or Verification(True, 0.42, 0.01, "recovered")),
        replayer=replayer,
        escalator=escalator,
        postmortem_writer=pm,
        store=store,
        config=EngineConfig(dry_run=dry_run),
    )
    return engine, escalator, pm, store, replayer


# -----------------------------------------------------------------------------
# Happy path
# -----------------------------------------------------------------------------

def test_approved_verified_and_replayed_resolves():
    """APPROVED -> verified -> full replay -> RESOLVED, no escalation."""
    engine, escalator, pm, store, replayer = _build(
        diagnosis=make_diagnosis(ActionType.RESTART_POD),
        verdict=PolicyVerdict(Decision.APPROVED, "high confidence"),
        verification=Verification(True, 0.42, 0.01, "recovered"),
        replay=ReplayResult(attempted=10, succeeded=10, failed=0, source="redpanda"),
        dry_run=False,
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.RESOLVED
    assert incident.action_result.executed is True
    assert replayer.called is True
    assert escalator.calls == []


# -----------------------------------------------------------------------------
# Diagnoser-driven branches
# -----------------------------------------------------------------------------

def test_no_op_diagnosis_closes_as_no_action():
    actuator = FakeActuator()
    engine, escalator, pm, store, replayer = _build(
        diagnosis=make_diagnosis(ActionType.NO_OP), actuator=actuator
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.NO_ACTION
    assert actuator.called is False
    assert replayer.called is False
    assert escalator.calls == []


def test_escalate_diagnosis_hands_to_human():
    actuator = FakeActuator()
    engine, escalator, pm, store, replayer = _build(
        diagnosis=make_diagnosis(ActionType.ESCALATE), actuator=actuator
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.ESCALATED
    assert actuator.called is False
    assert len(escalator.calls) == 1


# -----------------------------------------------------------------------------
# Policy gate branches (the safety boundary)
# -----------------------------------------------------------------------------

def test_denied_escalates_and_does_not_act():
    actuator = FakeActuator()
    engine, escalator, pm, store, replayer = _build(
        diagnosis=make_diagnosis(ActionType.RESTART_POD),
        verdict=PolicyVerdict(Decision.DENIED, "confidence below threshold"),
        actuator=actuator,
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.ESCALATED
    assert actuator.called is False
    assert "policy denied" in escalator.calls[0][1]


def test_requires_approval_escalates_and_does_not_act():
    actuator = FakeActuator()
    engine, escalator, pm, store, replayer = _build(
        diagnosis=make_diagnosis(ActionType.SCALE_UP),
        verdict=PolicyVerdict(Decision.REQUIRES_APPROVAL, "critical action needs sign-off"),
        actuator=actuator,
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.ESCALATED
    assert actuator.called is False
    assert "requires human approval" in escalator.calls[0][1]


# -----------------------------------------------------------------------------
# Safety: dry-run, failure, partial recovery
# -----------------------------------------------------------------------------

def test_dry_run_simulates_and_does_not_resolve():
    actuator = FakeActuator()
    engine, escalator, pm, store, replayer = _build(
        diagnosis=make_diagnosis(ActionType.RESTART_POD),
        verdict=PolicyVerdict(Decision.APPROVED, "ok"),
        actuator=actuator,
        dry_run=True,
    )
    [incident] = engine.run_once()

    assert actuator.called is True
    assert actuator.called_dry_run is True
    assert incident.outcome is Outcome.NO_ACTION  # simulated, not resolved
    assert replayer.called is False               # no replay on a simulated action


def test_action_error_escalates():
    failing = FakeActuator(
        ActionResult(
            action=ActionType.RESTART_POD, target="events-api",
            executed=False, dry_run=False, error="kubernetes api forbidden",
        )
    )
    engine, escalator, pm, store, replayer = _build(
        diagnosis=make_diagnosis(ActionType.RESTART_POD),
        verdict=PolicyVerdict(Decision.APPROVED, "ok"),
        actuator=failing, dry_run=False,
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.ESCALATED
    assert "action failed" in escalator.calls[0][1]


def test_acted_but_not_recovered_escalates():
    engine, escalator, pm, store, replayer = _build(
        diagnosis=make_diagnosis(ActionType.RESTART_POD),
        verdict=PolicyVerdict(Decision.APPROVED, "ok"),
        verification=Verification(False, 0.42, 0.40, "still high"),
        dry_run=False,
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.ESCALATED
    assert replayer.called is False  # no replay if the system didn't recover
    assert "did not recover" in escalator.calls[0][1]


def test_partial_replay_escalates_for_data_gap():
    """Service recovered but data recovery was incomplete -> escalate the gap."""
    engine, escalator, pm, store, replayer = _build(
        diagnosis=make_diagnosis(ActionType.RESTART_POD),
        verdict=PolicyVerdict(Decision.APPROVED, "ok"),
        verification=Verification(True, 0.42, 0.01, "recovered"),
        replay=ReplayResult(attempted=320, succeeded=300, failed=20, source="redpanda"),
        dry_run=False,
    )
    [incident] = engine.run_once()

    assert incident.outcome is Outcome.ESCALATED
    assert "partial data recovery" in escalator.calls[0][1]


# -----------------------------------------------------------------------------
# Always-on closeout: post-mortem + persistence
# -----------------------------------------------------------------------------

def test_postmortem_always_generated_and_incident_persisted():
    """Every path drafts a post-mortem and persists the incident."""
    engine, escalator, pm, store, replayer = _build(
        diagnosis=make_diagnosis(ActionType.NO_OP),
    )
    [incident] = engine.run_once()

    assert pm.called is True
    assert incident.postmortem is not None
    assert store.get(incident.id) is incident


def test_audit_trail_records_every_stage_on_happy_path():
    engine, *_ = _build(
        diagnosis=make_diagnosis(ActionType.RESTART_POD),
        verdict=PolicyVerdict(Decision.APPROVED, "ok"),
        verification=Verification(True, 0.42, 0.01, "recovered"),
        replay=ReplayResult(attempted=10, succeeded=10, failed=0, source="redpanda"),
        dry_run=False,
    )
    [incident] = engine.run_once()

    stages = [entry.stage for entry in incident.audit_trail]
    assert stages == ["diagnose", "policy", "act", "verify", "replay", "outcome", "postmortem"]
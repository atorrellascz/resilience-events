"""
Scenario tests -- end-to-end stories through the loop.

Unlike test_engine.py (which checks each branch in isolation), these read like
narratives. They are the scenarios worth walking an interviewer through, because
they map to real incidents on this platform:

  SCENARIO A -- "stuck pod": a compute-level fault. A pod is degraded; the loop
      restarts it, verifies recovery, replays the few in-flight requests, and
      resolves automatically.

  SCENARIO B -- "database down" (the headline): a data-level fault, exactly the
      chaos test we run by scaling SQL Server to zero. Restarting pods can't fix
      a dead database, so the safe move is to escalate to a human. After the
      human restores the database, the always-on replay recovers the requests
      that arrived during the outage from the durable write-ahead-log -- the
      "Veeam moment", no data lost -- and a post-mortem is drafted for review.

Both run entirely on fakes; no infrastructure required.
"""

from __future__ import annotations

from app.core.engine import EngineConfig, RemediationEngine
from app.core.models import (
    ActionType,
    Decision,
    Outcome,
    PolicyVerdict,
    ReplayResult,
    Severity,
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


# -----------------------------------------------------------------------------
# SCENARIO A -- stuck pod: automatic restart -> recover -> replay -> resolved
# -----------------------------------------------------------------------------

def test_scenario_stuck_pod_auto_remediates():
    escalator = RecordingEscalator()
    store = InMemoryIncidentStore()

    engine = RemediationEngine(
        # A pod is degraded: high error ratio on events-api.
        detector=FakeDetector([
            make_signal(severity=Severity.WARNING, description="pod degraded, elevated errors")
        ]),
        # The diagnoser is confident a restart will help.
        diagnoser=FakeDiagnoser(
            make_diagnosis(ActionType.RESTART_POD, confidence=0.92, target="events-api")
        ),
        # Policy approves a low-risk restart at high confidence.
        policy_gate=FakePolicyGate(PolicyVerdict(Decision.APPROVED, "restart is low-risk, confidence high")),
        actuator=FakeActuator(),  # default: executes successfully when not dry-run
        # After the restart the error ratio drops back to healthy.
        verifier=FakeVerifier(Verification(recovered=True, metric_before=0.30, metric_after=0.01)),
        # A handful of in-flight requests are recovered fully.
        replayer=FakeReplayer(ReplayResult(attempted=8, succeeded=8, failed=0, source="redpanda:events.wal")),
        escalator=escalator,
        postmortem_writer=FakePostMortemWriter(),
        store=store,
        config=EngineConfig(dry_run=False),  # autonomy enabled for this scenario
    )

    [incident] = engine.run_once()

    # The loop fixed it automatically, with no human involved.
    assert incident.outcome is Outcome.RESOLVED
    assert incident.action_result.action is ActionType.RESTART_POD
    assert incident.action_result.executed is True
    assert incident.verification.recovered is True
    assert incident.replay_result.complete is True
    assert escalator.calls == []

    # A post-mortem still exists for the record, not flagged as escalated.
    assert incident.postmortem is not None
    assert incident.postmortem.escalated is False
    assert store.get(incident.id) is incident


# -----------------------------------------------------------------------------
# SCENARIO B -- database down: escalate -> (human restores) -> replay -> recover
# This is the headline "data resilience" story.
# -----------------------------------------------------------------------------

def test_scenario_database_down_escalates_then_replays_after_recovery():
    escalator = RecordingEscalator()
    store = InMemoryIncidentStore()

    # Phase 1: the database is down. events-api is throwing errors because its
    # SQL Server dependency is unreachable. Restarting the pod won't help -- the
    # safe move is to escalate to a human.
    engine_outage = RemediationEngine(
        detector=FakeDetector([
            make_signal(
                severity=Severity.CRITICAL,
                description="SQL Server unreachable; events-api error ratio 42%",
            )
        ]),
        # The diagnoser recognizes this is not something a restart fixes and
        # defers to a human (proposes ESCALATE).
        diagnoser=FakeDiagnoser(
            make_diagnosis(ActionType.ESCALATE, confidence=0.40, target="events-api")
        ),
        policy_gate=FakePolicyGate(PolicyVerdict(Decision.APPROVED, "unused on escalate path")),
        actuator=FakeActuator(),
        verifier=FakeVerifier(Verification(False, 0.42, 0.42)),
        replayer=FakeReplayer(ReplayResult(0, 0, 0)),
        escalator=escalator,
        postmortem_writer=FakePostMortemWriter(),
        store=store,
        config=EngineConfig(dry_run=False),
    )

    [outage_incident] = engine_outage.run_once()

    # We escalated to a human and took no automated action against the data.
    assert outage_incident.outcome is Outcome.ESCALATED
    assert outage_incident.action_result is None  # never acted
    assert len(escalator.calls) == 1
    # The post-mortem is flagged as escalated.
    assert outage_incident.postmortem.escalated is True

    # Phase 2: a human restored the database. On the next cycle the system is
    # healthy again, and the always-on replay recovers the 320 requests that
    # arrived during the outage but were never persisted -- no data lost.
    escalator2 = RecordingEscalator()
    store2 = InMemoryIncidentStore()
    engine_recovered = RemediationEngine(
        # Detector now sees the system has recovered but flags the data gap to
        # be reconciled (a low-severity signal that drives the replay path).
        detector=FakeDetector([
            make_signal(severity=Severity.WARNING, description="post-recovery data reconciliation")
        ]),
        # A safe, approved no-risk action (here a restart to clear stale conns),
        # which verifies as recovered and then triggers the replay stage.
        diagnoser=FakeDiagnoser(
            make_diagnosis(ActionType.RESTART_POD, confidence=0.95, target="events-api")
        ),
        policy_gate=FakePolicyGate(PolicyVerdict(Decision.APPROVED, "safe reconciliation restart")),
        actuator=FakeActuator(),
        verifier=FakeVerifier(Verification(recovered=True, metric_before=0.20, metric_after=0.00)),
        # The Veeam moment: all 320 lost requests replayed from the WAL.
        replayer=FakeReplayer(
            ReplayResult(attempted=320, succeeded=320, failed=0, source="redpanda:events.wal")
        ),
        escalator=escalator2,
        postmortem_writer=FakePostMortemWriter(),
        store=store2,
        config=EngineConfig(dry_run=False),
    )

    [recovered_incident] = engine_recovered.run_once()

    # Full recovery: service healthy AND all data recovered, no escalation.
    assert recovered_incident.outcome is Outcome.RESOLVED
    assert recovered_incident.replay_result.attempted == 320
    assert recovered_incident.replay_result.succeeded == 320
    assert recovered_incident.replay_result.complete is True
    assert escalator2.calls == []

    # The post-mortem records the data recovery for the engineering team.
    assert recovered_incident.postmortem is not None
    assert "320" in recovered_incident.postmortem.data_recovery
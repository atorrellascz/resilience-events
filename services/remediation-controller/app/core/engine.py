"""
The remediation engine -- the orchestrator of the loop.

This is the core's centerpiece. It wires the stages together and runs the
sequence:

    detect -> diagnose -> gate -> act -> verify -> replay -> escalate
                                                       \\-> post-mortem (always)

It is completely agnostic of infrastructure: it knows nothing about Kubernetes,
Prometheus, LLMs, Redpanda, Redis, or Slack. It only knows the ports
(interfaces) and the domain model. That is what makes it unit-testable with
mocks and reusable across substrates.

Design rules enforced here:
  - The LLM never detects and never acts -- detection is the Detector (stats),
    action is gated by the PolicyGate and performed by the Actuator.
  - Fail-safe: anything that isn't an APPROVED, verified success ends in
    escalation to a human. When in doubt, escalate -- never "try and see".
  - REPLAY is always-on: after ANY successful recovery we attempt to recover
    lost data from the write-ahead-log. Data recovery is deterministic, not an
    LLM decision.
  - A POST-MORTEM is ALWAYS generated (even when escalated or no action taken),
    flagged for human review. Automated action must always produce a paper trail.
  - Every incident is persisted via the IncidentStore at the end.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.models import (
    ActionType,
    Decision,
    Incident,
    Outcome,
    Signal,
)
from app.core.ports import (
    Actuator,
    Detector,
    Diagnoser,
    Escalator,
    IncidentStore,
    PolicyGate,
    PostMortemWriter,
    Replayer,
    Verifier,
)


@dataclass
class EngineConfig:
    """
    Engine-level safety configuration.

    dry_run: when True (the DEFAULT), the actuator reports what it would do but
        changes nothing. Safe by default -- autonomy is opt-in.
    """
    dry_run: bool = True


class RemediationEngine:
    """Orchestrates one full pass of the remediation loop per detected signal."""

    def __init__(
        self,
        detector: Detector,
        diagnoser: Diagnoser,
        policy_gate: PolicyGate,
        actuator: Actuator,
        verifier: Verifier,
        replayer: Replayer,
        escalator: Escalator,
        postmortem_writer: PostMortemWriter,
        store: IncidentStore,
        config: EngineConfig | None = None,
    ) -> None:
        self._detector = detector
        self._diagnoser = diagnoser
        self._policy = policy_gate
        self._actuator = actuator
        self._verifier = verifier
        self._replayer = replayer
        self._escalator = escalator
        self._postmortem = postmortem_writer
        self._store = store
        self._config = config or EngineConfig()

    # -- Public API -----------------------------------------------------------

    def run_once(self) -> list[Incident]:
        """
        One detection cycle: find all current signals and process each through
        the loop. Returns the resulting Incidents (for logging / auditing).
        """
        signals = self._detector.detect()
        return [self._finish(self._process(self._new_incident(s))) for s in signals]

    # -- Internals ------------------------------------------------------------

    @staticmethod
    def _new_incident(signal: Signal) -> Incident:
        return Incident(id=str(uuid.uuid4()), signal=signal)

    def _process(self, incident: Incident) -> Incident:
        """Run a single incident through the full loop (up to outcome)."""

        # Stage 2 -- DIAGNOSE. The diagnoser proposes an action from the allowlist.
        diagnosis = self._diagnoser.diagnose(incident.signal)
        incident = incident.with_diagnosis(diagnosis)

        # A diagnosis of NO_OP means "nothing to do" -- close it out cleanly.
        if diagnosis.proposed_action is ActionType.NO_OP:
            return incident.with_outcome(Outcome.NO_ACTION, "diagnoser proposed no action")

        # A diagnosis of ESCALATE means the diagnoser itself defers to a human.
        if diagnosis.proposed_action is ActionType.ESCALATE:
            return self._do_escalate(incident, "diagnoser proposed escalation")

        # Stage 3 -- POLICY GATE. The safety boundary.
        verdict = self._policy.evaluate(incident)
        incident = incident.with_verdict(verdict)

        if verdict.decision is Decision.DENIED:
            return self._do_escalate(incident, f"policy denied: {verdict.reason}")

        if verdict.decision is Decision.REQUIRES_APPROVAL:
            # Human-in-the-loop: we do NOT act. We escalate for a human to decide.
            return self._do_escalate(
                incident, f"requires human approval: {verdict.reason}"
            )

        # verdict is APPROVED -> Stage 4 -- ACT.
        result = self._actuator.execute(incident, dry_run=self._config.dry_run)
        incident = incident.with_action_result(result)

        # If the action errored, escalate -- never pretend it worked.
        if result.error is not None:
            return self._do_escalate(incident, f"action failed: {result.error}")

        # In dry-run we don't claim a resolution; we record and stop here.
        if result.dry_run:
            return incident.with_outcome(
                Outcome.NO_ACTION, "dry-run: action simulated, not executed"
            )

        # Stage 5 -- VERIFY. Did it actually help?
        verification = self._verifier.verify(incident)
        incident = incident.with_verification(verification)

        if not verification.recovered:
            # Acted but didn't recover -> escalate (fail-safe). No replay on a
            # system that hasn't actually recovered.
            return self._do_escalate(incident, "action did not recover the signal")

        # Stage 6 -- REPLAY (always-on after a successful recovery). The Veeam
        # moment: recover data for requests lost during the outage.
        replay = self._replayer.replay(incident)
        incident = incident.with_replay_result(replay)

        if not replay.complete:
            # Service recovered but data recovery was partial -> a human should
            # know. We still resolved the outage, but flag the data gap.
            return self._do_escalate(
                incident,
                f"partial data recovery: {replay.succeeded}/{replay.attempted} replayed",
            )

        return incident.with_outcome(
            Outcome.RESOLVED,
            f"recovered and replayed {replay.succeeded}/{replay.attempted} requests",
        )

    def _do_escalate(self, incident: Incident, reason: str) -> Incident:
        """Escalate to a human and mark the incident accordingly."""
        self._escalator.escalate(incident, reason)
        return incident.with_outcome(Outcome.ESCALATED, reason)

    def _finish(self, incident: Incident) -> Incident:
        """
        Closeout shared by every path: ALWAYS draft a post-mortem for human
        review, then persist the incident. This runs no matter how the incident
        ended -- resolved, escalated, or no-action -- so there is always a
        paper trail.
        """
        postmortem = self._postmortem.write(incident)
        incident = incident.with_postmortem(postmortem)
        self._store.save(incident)
        return incident
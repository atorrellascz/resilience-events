"""
Ports (interfaces) for the remediation loop.

These are the contracts each stage must satisfy. The engine depends ONLY on
these abstractions, never on concrete implementations -- that is the dependency
inversion that lets us swap a mock LLM for Azure OpenAI or Claude, a Kubernetes
actuator for a no-op, or an in-memory store for MongoDB, without touching the
loop's logic.

We use `typing.Protocol` (structural typing) rather than ABCs: an adapter just
needs the right method shape to qualify. This keeps adapters decoupled -- they
don't even have to import this module to be compatible, which matters if the
core is ever extracted into its own package.

Mapping of ports to the real infrastructure they will be backed by (later):
    Detector         -> Prometheus (statistical thresholds on metrics)
    Diagnoser        -> mock now; Azure OpenAI / Claude later (swap the adapter)
    PolicyGate       -> pure Python rules from declarative config
    Actuator         -> Kubernetes API (dry-run first)
    Verifier         -> Prometheus (re-check the metric)
    Replayer         -> Redpanda (re-consume the durable write-ahead-log)
    Escalator        -> Slack via Alertmanager (the same channel as system alerts)
    PostMortemWriter -> mock now; LLM later (drafts the first report)
    IncidentStore    -> in-memory now; Redis (active) + MongoDB (history) later
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.models import (
    ActionResult,
    Diagnosis,
    Incident,
    PolicyVerdict,
    PostMortem,
    ReplayResult,
    Signal,
    Verification,
)


@runtime_checkable
class Detector(Protocol):
    """
    Stage 1 -- DETECT. Deterministic, statistical. NEVER an LLM.

    Returns the signals currently worth acting on (e.g. metrics that crossed a
    statistical threshold). Returning an empty list means "all healthy".
    """

    def detect(self) -> list[Signal]:
        ...


@runtime_checkable
class Diagnoser(Protocol):
    """
    Stage 2 -- DIAGNOSE. May be backed by an LLM (or a deterministic mock).

    Given a signal, proposes ONE action from the allowlist with a confidence
    and rationale. It only suggests; it neither decides nor acts. Implementations
    must constrain the LLM to the allowlist (ActionType) -- a suggestion outside
    it is a bug in the adapter, not a new capability.
    """

    def diagnose(self, signal: Signal) -> Diagnosis:
        ...


@runtime_checkable
class PolicyGate(Protocol):
    """
    Stage 3 -- POLICY. Pure, deterministic gate. The safety boundary.

    Decides whether a proposed action may run automatically, needs human
    approval, or is denied -- based on confidence thresholds, the allowlist,
    cooldowns, rate limits, severity, etc. This is where "autonomy with
    guardrails" is enforced. Must be auditable and side-effect free.
    """

    def evaluate(self, incident: Incident) -> PolicyVerdict:
        ...


@runtime_checkable
class Actuator(Protocol):
    """
    Stage 4 -- ACT. The only stage that touches the outside world to change it.

    Executes an approved action (e.g. via the Kubernetes API). Must honor a
    dry-run mode (execute nothing, report what it *would* do). Must never raise
    past its own boundary -- failures come back as an ActionResult with `error`.
    """

    def execute(self, incident: Incident, dry_run: bool) -> ActionResult:
        ...


@runtime_checkable
class Verifier(Protocol):
    """
    Stage 5 -- VERIFY. Did the action actually help?

    Re-checks the signal's metric after the action and reports whether the
    system recovered. Drives the decision to proceed to replay vs escalate.
    """

    def verify(self, incident: Incident) -> Verification:
        ...


@runtime_checkable
class Replayer(Protocol):
    """
    Stage 6 -- REPLAY (the "Veeam moment"). Always-on after a successful recovery.

    Re-processes requests that were accepted during the outage but never
    persisted, reading them from a durable write-ahead-log (Redpanda). Reports
    how complete the data recovery was. This is deterministic data recovery,
    NOT an LLM decision -- which is why replay is a stage, not an allowlist action.
    """

    def replay(self, incident: Incident) -> ReplayResult:
        ...


@runtime_checkable
class Escalator(Protocol):
    """
    ESCALATE -- hand off to a human.

    Notifies a human (via the same Slack/Alertmanager channel the rest of the
    system uses) when an action is unsafe, denied, failed, or only partially
    recovered. Reuses existing alerting infrastructure rather than inventing a
    new channel.
    """

    def escalate(self, incident: Incident, reason: str) -> None:
        ...


@runtime_checkable
class PostMortemWriter(Protocol):
    """
    POST-MORTEM -- always runs at the end of the loop.

    Drafts the first version of the incident report (LLM-backed later, mock now)
    for the engineering team to review. Receives the fully-enriched incident so
    it can summarize detection, action, verification, and data recovery.
    """

    def write(self, incident: Incident) -> PostMortem:
        ...


@runtime_checkable
class IncidentStore(Protocol):
    """
    PERSISTENCE -- not a loop stage, but the loop's memory.

    Saves incidents so they can be audited and so post-mortems can be reviewed
    later. In production this is split by lifecycle: Redis for active incidents
    (fast, plus the replay queue and cooldowns) and MongoDB for closed incidents
    and post-mortems (durable, queryable history). The core only sees this one
    interface; which store is behind it is an adapter concern.
    """

    def save(self, incident: Incident) -> None:
        ...

    def get(self, incident_id: str) -> Incident | None:
        ...
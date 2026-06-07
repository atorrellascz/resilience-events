"""
Domain model for the remediation loop.

────────────────────────────────────────────────────────────────────────────
THE REMEDIATION LOOP — the big picture
────────────────────────────────────────────────────────────────────────────
This service watches the platform, and when something goes wrong it runs a
closed, guardrailed loop to fix it (or safely hand it to a human). The loop is
the heart of the project's "data resilience" story:

    DETECT  -> a deterministic, statistical signal (NEVER an LLM) says
              "events-api error ratio is 42%, its database is not responding".

    DIAGNOSE -> an LLM (or a deterministic mock) proposes ONE action from a
              fixed ALLOWLIST, with a confidence and a rationale. It only
              suggests -- it does not decide and does not act.

    POLICY  -> a deterministic gate decides: APPROVED (act automatically),
              REQUIRES_APPROVAL (human-in-the-loop), or DENIED. This is the
              safety boundary where "autonomy with guardrails" lives.

    ACT     -> the actuator performs the approved action against the platform
              (e.g. the Kubernetes API). Honors dry-run.

    VERIFY  -> did the metric actually recover? If not, we do not pretend it did.

    REPLAY  -> (always-on after a successful recovery) the "Veeam moment".
              While the dependency was down, incoming requests may have been
              accepted but never persisted. We re-process those lost requests
              from a durable write-ahead-log (Redpanda) so NO DATA IS LOST --
              the same idea behind backup & restore.

    ESCALATE -> if anything is unsafe, denied, failed, or only partially
              recovered, a human is notified through the SAME alerting channel
              the rest of the system uses (Slack via Alertmanager).

    POST-MORTEM -> a first-draft incident report is ALWAYS generated (the LLM
              writes it) for the engineering team to review. If the incident
              was escalated, the post-mortem is flagged as such.

────────────────────────────────────────────────────────────────────────────
WHY THIS MODEL LOOKS LIKE THIS
────────────────────────────────────────────────────────────────────────────
The `Incident` is the single object that flows through every stage. Each stage
reads it and returns an ENRICHED COPY (the model is frozen/immutable -- we never
mutate in place). This gives us a complete, tamper-evident timeline: at any
point you can see exactly what was detected, what the LLM suggested, what the
gate decided, what was done, whether it recovered, what was replayed, and the
post-mortem. That auditability is essential for a system that acts on its own.

No infrastructure concerns leak in here -- no Kubernetes, no Prometheus, no LLM
SDK, no Redis, no Redpanda. This is pure domain: the language the loop speaks
internally. Infrastructure lives behind ports (see ports.py) and is supplied by
adapters, so the core stays testable in memory and reusable across substrates.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum


def _now() -> datetime:
    """UTC timestamp. Centralized so tests can reason about ordering."""
    return datetime.now(timezone.utc)


# -----------------------------------------------------------------------------
# Enums -- the closed vocabularies of the loop. Using enums (not free strings)
# means an invalid state is unrepresentable, and the allowlist of actions is
# enforced by the type system, not by hope.
# -----------------------------------------------------------------------------

class Severity(str, Enum):
    """How bad the detected signal is. Drives policy decisions downstream."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ActionType(str, Enum):
    """
    The ALLOWLIST of remediation actions -- the single source of truth for what
    the system is even *capable* of attempting. The LLM can only choose from
    this set; it cannot invent an action. Adding a capability is a deliberate,
    reviewed change here, never an emergent LLM behavior.

    Two families:
      - Compute-failure actions  -- a pod is stuck/overloaded:
            RESTART_POD, SCALE_UP, SCALE_DOWN
      - Safe defaults / handoff:
            NO_OP (do nothing), ESCALATE (defer to a human)

    Note: REPLAY is intentionally NOT here. Replay is not a remediation the LLM
    chooses -- it is an always-on recovery STAGE that runs after any successful
    recovery (see ReplayResult and the engine). Keeping it out of the allowlist
    prevents the LLM from ever "deciding" to replay data; data recovery is a
    deterministic, post-recovery step, not an LLM judgment call.
    """
    NO_OP = "no_op"
    RESTART_POD = "restart_pod"
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    ESCALATE = "escalate"


class Decision(str, Enum):
    """What the policy gate concluded about a proposed action."""
    APPROVED = "approved"                     # safe to execute automatically
    REQUIRES_APPROVAL = "requires_approval"   # needs a human to confirm first
    DENIED = "denied"                         # not allowed (policy/confidence/cooldown)


class Outcome(str, Enum):
    """How the whole incident ended."""
    PENDING = "pending"           # still being processed
    RESOLVED = "resolved"         # action taken, verified, and (if needed) data replayed
    ESCALATED = "escalated"       # handed to a human
    FAILED = "failed"             # action taken but did not help
    NO_ACTION = "no_action"       # nothing needed / nothing safe to do


# -----------------------------------------------------------------------------
# Stage payloads -- each stage attaches one of these to the Incident.
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Signal:
    """
    What the detector observed. Created by the Detector stage.
    Deterministic and infrastructure-derived (e.g. a metric crossing a
    statistical threshold) -- never produced by an LLM.
    """
    source: str                    # e.g. "events-api"
    metric: str                    # e.g. "http_error_ratio"
    value: float                   # observed value, e.g. 0.42
    threshold: float               # the threshold it crossed, e.g. 0.05
    severity: Severity
    description: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Diagnosis:
    """
    What the diagnoser proposed. Created by the Diagnoser stage (LLM or mock).
    The LLM's role ends here: it SUGGESTS an action from the allowlist with a
    confidence and a rationale. It does not decide and does not act.
    """
    proposed_action: ActionType
    confidence: float              # 0.0-1.0; the gate uses this as one input
    rationale: str                 # human-readable reasoning (for the audit trail)
    target: str = ""               # what the action applies to, e.g. "events-api"


@dataclass(frozen=True)
class PolicyVerdict:
    """What the policy gate decided about the diagnosis."""
    decision: Decision
    reason: str                    # why -- e.g. "confidence 0.62 below threshold 0.80"


@dataclass(frozen=True)
class ActionResult:
    """What the actuator did and what happened. Created by the Actuator stage."""
    action: ActionType
    target: str
    executed: bool                 # False in dry-run or when denied
    dry_run: bool
    detail: str = ""               # e.g. "deleted pod events-api-abc123"
    error: str | None = None       # populated if the action raised


@dataclass(frozen=True)
class Verification:
    """Whether the action actually helped. Created by the Verifier stage."""
    recovered: bool
    metric_before: float
    metric_after: float
    detail: str = ""


@dataclass(frozen=True)
class ReplayResult:
    """
    The outcome of the data-replay stage -- the "Veeam moment".

    After a dependency recovers, requests that arrived during the outage may
    have been accepted but never persisted. The Replayer re-processes them from
    a durable write-ahead-log (Redpanda). This records how complete that data
    recovery was -- the headline number in the post-mortem.
    """
    attempted: int                 # how many lost requests we found to replay
    succeeded: int                 # how many were successfully re-processed
    failed: int                    # how many could not be replayed
    source: str = ""               # where they were replayed from, e.g. "redpanda:events.wal"
    detail: str = ""

    @property
    def complete(self) -> bool:
        """True when every lost request was recovered (no data loss)."""
        return self.failed == 0


@dataclass(frozen=True)
class PostMortem:
    """
    The first-draft incident report. ALWAYS generated at the end of the loop
    (the LLM writes the first version) for the engineering team to review.

    `escalated` mirrors whether a human was pulled in, so the report is clearly
    flagged for those cases. `reviewed` starts False -- a human flips it after
    reviewing. This is the artifact that turns an automated action into
    organizational learning.
    """
    summary: str                   # what happened, in prose (LLM-drafted)
    timeline: tuple[str, ...]      # condensed human-readable timeline
    data_recovery: str             # replay outcome in words, e.g. "320/320 recovered"
    escalated: bool                # was a human involved?
    reviewed: bool = False         # flipped True once engineering signs off
    generated_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class AuditEntry:
    """One line in the incident's timeline. Append-only."""
    stage: str
    message: str
    at: datetime = field(default_factory=_now)


# -----------------------------------------------------------------------------
# The Incident -- the aggregate that flows through the loop.
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Incident:
    """
    The central object of the remediation loop (see the module docstring for
    the full loop description).

    It is IMMUTABLE: each stage returns an enriched copy via the `with_*`
    helpers, so the object's history is never lost and every transition is
    explicit and auditable. The `audit_trail` is the append-only timeline; the
    optional stage fields (`diagnosis`, `verdict`, ...) are filled in as the
    incident progresses. An incident that only has a `signal` is one that has
    just been detected and not yet processed.
    """
    id: str
    signal: Signal
    created_at: datetime = field(default_factory=_now)

    diagnosis: Diagnosis | None = None
    verdict: PolicyVerdict | None = None
    action_result: ActionResult | None = None
    verification: Verification | None = None
    replay_result: ReplayResult | None = None
    postmortem: PostMortem | None = None
    outcome: Outcome = Outcome.PENDING

    audit_trail: tuple[AuditEntry, ...] = field(default_factory=tuple)

    # -- Enrichment helpers: return a NEW Incident with one stage filled in,
    #    plus an audit entry. Never mutate self. --

    def _audit(self, stage: str, message: str) -> tuple[AuditEntry, ...]:
        return self.audit_trail + (AuditEntry(stage=stage, message=message),)

    def with_diagnosis(self, diagnosis: Diagnosis) -> "Incident":
        return replace(
            self,
            diagnosis=diagnosis,
            audit_trail=self._audit(
                "diagnose",
                f"proposed {diagnosis.proposed_action.value} "
                f"(confidence {diagnosis.confidence:.2f}) on "
                f"{diagnosis.target or self.signal.source}",
            ),
        )

    def with_verdict(self, verdict: PolicyVerdict) -> "Incident":
        return replace(
            self,
            verdict=verdict,
            audit_trail=self._audit("policy", f"{verdict.decision.value}: {verdict.reason}"),
        )

    def with_action_result(self, result: ActionResult) -> "Incident":
        msg = f"{result.action.value} on {result.target} "
        msg += "executed" if result.executed else ("dry-run" if result.dry_run else "skipped")
        if result.error:
            msg += f" -- error: {result.error}"
        elif result.detail:
            msg += f" -- {result.detail}"
        return replace(self, action_result=result, audit_trail=self._audit("act", msg))

    def with_verification(self, verification: Verification) -> "Incident":
        msg = (
            f"{'recovered' if verification.recovered else 'not recovered'} "
            f"({verification.metric_before:.3f} -> {verification.metric_after:.3f})"
        )
        return replace(
            self, verification=verification, audit_trail=self._audit("verify", msg)
        )

    def with_replay_result(self, replay: ReplayResult) -> "Incident":
        msg = (
            f"replayed {replay.succeeded}/{replay.attempted} lost requests"
            + (f", {replay.failed} failed" if replay.failed else "")
            + (f" from {replay.source}" if replay.source else "")
        )
        return replace(self, replay_result=replay, audit_trail=self._audit("replay", msg))

    def with_postmortem(self, postmortem: PostMortem) -> "Incident":
        flag = " (escalated)" if postmortem.escalated else ""
        return replace(
            self,
            postmortem=postmortem,
            audit_trail=self._audit("postmortem", f"draft generated{flag}, awaiting review"),
        )

    def with_outcome(self, outcome: Outcome, note: str = "") -> "Incident":
        msg = outcome.value + (f": {note}" if note else "")
        return replace(self, outcome=outcome, audit_trail=self._audit("outcome", msg))
"""
RiskBasedPolicyGate -- the safety boundary of the loop.

The diagnoser SUGGESTS an action; this gate DECIDES whether it may run
automatically, needs a human's sign-off, or is denied outright. This is where
"autonomy with guardrails" actually lives.

DESIGN -- declarative, risk-based policy:
    The policy is CONFIGURATION, not hardcoded if/else. Each allowlist action is
    assigned a RiskLevel, and the config states the highest risk level that may
    be auto-approved, the confidence threshold, and a cooldown. This lets a
    permissive dev environment and a strict prod environment share the same code
    and differ only in config -- and lets an operator tune the policy without a
    code change.

Decision logic (evaluated in order, fail-safe at every step):
    1. Re-validate the action against the allowlist. Defense in depth: the
       diagnoser already constrains it, but the gate does NOT trust upstream.
       Off-allowlist -> DENIED.
    2. ESCALATE is always allowed through as "requires approval" -- it is the
       explicit hand-to-human signal, never auto-executed.
    3. Cooldown: if we acted on this same target+action too recently, DENY to
       prevent remediation loops / flapping.
    4. Confidence below threshold -> REQUIRES_APPROVAL (a human decides; we do
       not silently discard a low-confidence suggestion).
    5. Risk above the auto-approve ceiling -> REQUIRES_APPROVAL.
    6. Otherwise -> APPROVED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum

from app.core.models import ActionType, Decision, Incident, PolicyVerdict


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RiskLevel(IntEnum):
    """
    Ordered risk of an action. IntEnum so we can compare with <=. The ordering
    is the whole point: 'auto-approve up to level N'.
    """
    NONE = 0        # no-op: harmless
    LOW = 1         # restart a single pod: self-healing, low blast radius
    MEDIUM = 2      # scale up: adds resources, costs money but not disruptive
    HIGH = 3        # scale down: can drop capacity / cause disruption
    CRITICAL = 4    # reserved for future destructive actions; never auto


# Default risk assignment for the allowlist. Conservative and explicit.
_DEFAULT_RISK: dict[ActionType, RiskLevel] = {
    ActionType.NO_OP: RiskLevel.NONE,
    ActionType.RESTART_POD: RiskLevel.LOW,
    ActionType.SCALE_UP: RiskLevel.MEDIUM,
    ActionType.SCALE_DOWN: RiskLevel.HIGH,
    ActionType.ESCALATE: RiskLevel.NONE,  # handing to a human is itself safe
}


@dataclass(frozen=True)
class PolicyConfig:
    """
    The declarative policy. Tune per environment; the code never changes.

    confidence_threshold: minimum diagnosis confidence to auto-approve. Below it,
        the action is not denied -- it goes to a human (REQUIRES_APPROVAL).
    auto_approve_max_risk: the highest RiskLevel that may run automatically.
        Anything riskier requires human approval. A Staff-sensible default is
        LOW: self-healing restarts run on their own; anything that changes
        capacity waits for a human.
    cooldown: minimum time between automated actions on the same target+action,
        to prevent remediation loops / flapping.
    risk: per-action risk map (defaults provided; override per environment).
    """
    confidence_threshold: float = 0.80
    auto_approve_max_risk: RiskLevel = RiskLevel.LOW
    cooldown: timedelta = timedelta(minutes=10)
    risk: dict[ActionType, RiskLevel] = field(default_factory=lambda: dict(_DEFAULT_RISK))

    def risk_of(self, action: ActionType) -> RiskLevel:
        # Unknown actions are treated as maximally risky -- fail-safe.
        return self.risk.get(action, RiskLevel.CRITICAL)


class RiskBasedPolicyGate:
    """
    Stateful gate: remembers recent automated actions to enforce cooldowns.
    Satisfies the PolicyGate port structurally.

    The cooldown memory is intentionally simple and in-process here; a
    distributed deployment would back it with Redis (the same active-state store
    used for in-flight incidents), but that is an adapter concern -- the decision
    logic is identical.
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self._config = config or PolicyConfig()
        # (target, action) -> timestamp of last automated action
        self._last_action: dict[tuple[str, ActionType], datetime] = {}

    def evaluate(self, incident: Incident) -> PolicyVerdict:
        diagnosis = incident.diagnosis
        if diagnosis is None:
            # Should never happen -- the engine diagnoses before gating.
            return PolicyVerdict(Decision.DENIED, "no diagnosis to evaluate")

        action = diagnosis.proposed_action
        target = diagnosis.target or incident.signal.source
        cfg = self._config

        # 1. Defense in depth: re-validate against the allowlist.
        if action not in ActionType:
            return PolicyVerdict(Decision.DENIED, f"action {action!r} not in allowlist")

        # 2. ESCALATE is the explicit hand-to-human; route it as requires-approval.
        if action is ActionType.ESCALATE:
            return PolicyVerdict(
                Decision.REQUIRES_APPROVAL, "diagnoser deferred to a human"
            )

        # NO_OP needs no gating -- approve it (the engine treats it as no action).
        if action is ActionType.NO_OP:
            return PolicyVerdict(Decision.APPROVED, "no-op requires no intervention")

        # 3. Cooldown: avoid acting repeatedly on the same target+action.
        last = self._last_action.get((target, action))
        if last is not None and _now() - last < cfg.cooldown:
            remaining = cfg.cooldown - (_now() - last)
            return PolicyVerdict(
                Decision.DENIED,
                f"cooldown active for {action.value} on {target} "
                f"({int(remaining.total_seconds())}s remaining)",
            )

        # 4. Confidence below threshold -> human decides (not discarded).
        if diagnosis.confidence < cfg.confidence_threshold:
            return PolicyVerdict(
                Decision.REQUIRES_APPROVAL,
                f"confidence {diagnosis.confidence:.2f} below threshold "
                f"{cfg.confidence_threshold:.2f}",
            )

        # 5. Risk above the auto-approve ceiling -> human approval required.
        risk = cfg.risk_of(action)
        if risk > cfg.auto_approve_max_risk:
            return PolicyVerdict(
                Decision.REQUIRES_APPROVAL,
                f"{action.value} risk {risk.name} exceeds auto-approve ceiling "
                f"{cfg.auto_approve_max_risk.name}",
            )

        # 6. Approved. Record the action time for cooldown tracking.
        self._last_action[(target, action)] = _now()
        return PolicyVerdict(
            Decision.APPROVED,
            f"{action.value} approved (risk {risk.name}, "
            f"confidence {diagnosis.confidence:.2f})",
        )

"""
Tests for the RiskBasedPolicyGate -- the safety boundary.

Covers each decision rule: allowlist re-validation, escalate routing, cooldown,
confidence threshold (-> requires approval, not denied), and the risk ceiling.
The gate is the half of "autonomy with guardrails" that decides; these tests
pin down exactly when the system acts on its own vs waits for a human.
"""

from __future__ import annotations

from datetime import timedelta

from app.adapters.policy.gate import PolicyConfig, RiskBasedPolicyGate, RiskLevel
from app.core.models import (
    ActionType,
    Decision,
    Diagnosis,
    Incident,
    Severity,
    Signal,
)


def _incident(action: ActionType, confidence: float = 0.9, target: str = "events-api") -> Incident:
    sig = Signal(target, "http_error_ratio", 0.42, 0.05, Severity.WARNING, "errors")
    diag = Diagnosis(proposed_action=action, confidence=confidence, rationale="t", target=target)
    return Incident(id="i1", signal=sig).with_diagnosis(diag)


# -----------------------------------------------------------------------------
# Auto-approval within the risk ceiling
# -----------------------------------------------------------------------------

def test_low_risk_high_confidence_is_approved():
    """restart_pod (LOW) at high confidence, default ceiling LOW -> APPROVED."""
    gate = RiskBasedPolicyGate()
    v = gate.evaluate(_incident(ActionType.RESTART_POD, confidence=0.95))
    assert v.decision is Decision.APPROVED


def test_no_op_is_approved():
    gate = RiskBasedPolicyGate()
    v = gate.evaluate(_incident(ActionType.NO_OP))
    assert v.decision is Decision.APPROVED


# -----------------------------------------------------------------------------
# Risk ceiling -> requires approval
# -----------------------------------------------------------------------------

def test_medium_risk_exceeds_default_ceiling_requires_approval():
    """scale_up (MEDIUM) above the default LOW ceiling -> REQUIRES_APPROVAL."""
    gate = RiskBasedPolicyGate()
    v = gate.evaluate(_incident(ActionType.SCALE_UP, confidence=0.95))
    assert v.decision is Decision.REQUIRES_APPROVAL
    assert "exceeds auto-approve ceiling" in v.reason


def test_high_risk_scale_down_requires_approval():
    gate = RiskBasedPolicyGate()
    v = gate.evaluate(_incident(ActionType.SCALE_DOWN, confidence=0.99))
    assert v.decision is Decision.REQUIRES_APPROVAL


def test_raising_ceiling_allows_medium_risk_auto():
    """With a MEDIUM ceiling, scale_up auto-approves -- config drives behavior."""
    gate = RiskBasedPolicyGate(PolicyConfig(auto_approve_max_risk=RiskLevel.MEDIUM))
    v = gate.evaluate(_incident(ActionType.SCALE_UP, confidence=0.95))
    assert v.decision is Decision.APPROVED


# -----------------------------------------------------------------------------
# Confidence threshold -> requires approval (NOT denied)
# -----------------------------------------------------------------------------

def test_low_confidence_requires_approval_not_denied():
    gate = RiskBasedPolicyGate()
    v = gate.evaluate(_incident(ActionType.RESTART_POD, confidence=0.50))
    assert v.decision is Decision.REQUIRES_APPROVAL
    assert "below threshold" in v.reason


# -----------------------------------------------------------------------------
# Escalate routing
# -----------------------------------------------------------------------------

def test_escalate_action_routes_to_requires_approval():
    gate = RiskBasedPolicyGate()
    v = gate.evaluate(_incident(ActionType.ESCALATE, confidence=0.4))
    assert v.decision is Decision.REQUIRES_APPROVAL
    assert "deferred to a human" in v.reason


# -----------------------------------------------------------------------------
# Cooldown -> denied on repeat
# -----------------------------------------------------------------------------

def test_cooldown_denies_repeat_action_on_same_target():
    gate = RiskBasedPolicyGate(PolicyConfig(cooldown=timedelta(minutes=10)))
    first = gate.evaluate(_incident(ActionType.RESTART_POD, confidence=0.95))
    assert first.decision is Decision.APPROVED  # first one acts

    second = gate.evaluate(_incident(ActionType.RESTART_POD, confidence=0.95))
    assert second.decision is Decision.DENIED   # within cooldown
    assert "cooldown active" in second.reason


def test_cooldown_does_not_block_different_target():
    gate = RiskBasedPolicyGate()
    gate.evaluate(_incident(ActionType.RESTART_POD, confidence=0.95, target="events-api"))
    other = gate.evaluate(_incident(ActionType.RESTART_POD, confidence=0.95, target="catalog-api"))
    assert other.decision is Decision.APPROVED  # different target, no cooldown


# -----------------------------------------------------------------------------
# Defense in depth: no diagnosis
# -----------------------------------------------------------------------------

def test_missing_diagnosis_is_denied():
    sig = Signal("events-api", "m", 1.0, 0.1, Severity.WARNING, "x")
    bare = Incident(id="i", signal=sig)  # no diagnosis attached
    v = RiskBasedPolicyGate().evaluate(bare)
    assert v.decision is Decision.DENIED

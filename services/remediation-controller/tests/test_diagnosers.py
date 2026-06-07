"""
Tests for the Diagnoser adapters -- both the deterministic mock and the
LLM-backed one. The most important tests here are the guardrail tests: that an
LLM hallucinating an action outside the allowlist is rejected and falls back to
ESCALATE. That is the safety property that lets us put an LLM in the loop at all.
"""

from __future__ import annotations

from app.adapters.diagnosers.llm import LLMDiagnoser
from app.adapters.diagnosers.llm_client import StaticLLMClient
from app.adapters.diagnosers.mock import MockDiagnoser
from app.core.models import ActionType, Severity, Signal


def _sig(metric="http_error_ratio", desc="", severity=Severity.WARNING, source="events-api"):
    return Signal(
        source=source, metric=metric, value=0.42, threshold=0.05,
        severity=severity, description=desc,
    )


# -----------------------------------------------------------------------------
# MockDiagnoser -- hybrid fault-type + severity reasoning
# -----------------------------------------------------------------------------

def test_mock_database_failure_escalates():
    d = MockDiagnoser().diagnose(
        _sig(metric="db_ping", desc="SQL Server connection refused", severity=Severity.CRITICAL)
    )
    assert d.proposed_action is ActionType.ESCALATE
    assert d.confidence > 0.5


def test_mock_pod_error_restarts():
    d = MockDiagnoser().diagnose(
        _sig(metric="http_error_ratio", desc="elevated 5xx error ratio", severity=Severity.WARNING)
    )
    assert d.proposed_action is ActionType.RESTART_POD


def test_mock_saturation_scales_up():
    d = MockDiagnoser().diagnose(
        _sig(metric="p99_latency", desc="high latency under CPU saturation", severity=Severity.WARNING)
    )
    assert d.proposed_action is ActionType.SCALE_UP


def test_mock_info_signal_is_no_op():
    d = MockDiagnoser().diagnose(
        _sig(metric="requests_total", desc="nominal traffic", severity=Severity.INFO)
    )
    assert d.proposed_action is ActionType.NO_OP


def test_mock_unrecognized_escalates():
    d = MockDiagnoser().diagnose(
        _sig(metric="weird_metric", desc="something unfamiliar", severity=Severity.WARNING)
    )
    assert d.proposed_action is ActionType.ESCALATE


def test_mock_severity_modulates_confidence():
    crit = MockDiagnoser().diagnose(_sig(desc="elevated 5xx error ratio", severity=Severity.CRITICAL))
    info = MockDiagnoser().diagnose(_sig(desc="elevated 5xx error ratio", severity=Severity.INFO))
    assert crit.confidence > info.confidence


# -----------------------------------------------------------------------------
# LLMDiagnoser -- parsing well-formed responses
# -----------------------------------------------------------------------------

def test_llm_parses_valid_json_action():
    client = StaticLLMClient('{"action": "restart_pod", "confidence": 0.88, "rationale": "pod is wedged"}')
    d = LLMDiagnoser(client).diagnose(_sig())
    assert d.proposed_action is ActionType.RESTART_POD
    assert d.confidence == 0.88
    assert "wedged" in d.rationale


def test_llm_clamps_out_of_range_confidence():
    client = StaticLLMClient('{"action": "scale_up", "confidence": 9.9, "rationale": "x"}')
    d = LLMDiagnoser(client).diagnose(_sig())
    assert d.proposed_action is ActionType.SCALE_UP
    assert d.confidence == 1.0


def test_llm_extracts_action_from_loose_text():
    """If JSON fails but the text names exactly one allowlist action, accept it."""
    client = StaticLLMClient("I recommend escalate because this looks like a data issue.")
    d = LLMDiagnoser(client).diagnose(_sig())
    assert d.proposed_action is ActionType.ESCALATE


# -----------------------------------------------------------------------------
# LLMDiagnoser -- THE GUARDRAIL: reject anything off-allowlist
# -----------------------------------------------------------------------------

def test_llm_hallucinated_action_is_rejected_and_escalates():
    """The model invents a destructive action not on the allowlist -> ESCALATE."""
    client = StaticLLMClient('{"action": "delete_database", "confidence": 0.99, "rationale": "just do it"}')
    d = LLMDiagnoser(client).diagnose(_sig())
    assert d.proposed_action is ActionType.ESCALATE  # NOT delete_database
    assert "did not yield a single valid allowlist action" in d.rationale


def test_llm_ambiguous_multiple_actions_escalates():
    """If the model names several allowlist actions, that's ambiguous -> ESCALATE."""
    client = StaticLLMClient("maybe restart_pod or scale_up, hard to say")
    d = LLMDiagnoser(client).diagnose(_sig())
    assert d.proposed_action is ActionType.ESCALATE


def test_llm_empty_response_escalates():
    client = StaticLLMClient("")
    d = LLMDiagnoser(client).diagnose(_sig())
    assert d.proposed_action is ActionType.ESCALATE


def test_llm_garbage_response_escalates():
    client = StaticLLMClient("asdf qwer zxcv no actions here")
    d = LLMDiagnoser(client).diagnose(_sig())
    assert d.proposed_action is ActionType.ESCALATE
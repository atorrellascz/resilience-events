"""
LLMDiagnoser -- an LLM-backed Diagnoser, constrained to the allowlist.

This is where the "AI" lives, and where the most important guardrail lives with
it. An LLM returns free text; this adapter is responsible for turning that text
into exactly one allowlist action -- or rejecting it. The model proposes in
natural language; a STRICT PARSER forces the result into ActionType or falls
back to ESCALATE. The model can never widen what the system is allowed to do,
no matter what it writes.

Flow:
    1. Build a tightly-scoped prompt that tells the model the ONLY actions it may
       choose from, and asks for a structured answer.
    2. Call the injected LLMClient (mock, OpenAI, or Claude -- the diagnoser
       doesn't know or care which).
    3. Parse defensively:
         - extract a known action token; anything off-allowlist is discarded
         - if nothing valid is found -> ESCALATE (fail-safe, never guess)
         - clamp confidence to [0, 1]

Why a separate parser instead of trusting structured output? Because trusting
the model is exactly the failure mode we're designing against. Even with JSON
mode, the safe system treats the model's output as untrusted input and validates
it against the allowlist itself.
"""

from __future__ import annotations

import json
import re

from app.adapters.diagnosers.llm_client import LLMClient
from app.core.models import ActionType, Diagnosis, Signal

# The only actions the model is allowed to choose. Built from the enum so it can
# never drift from the real allowlist.
_ALLOWED = {a.value for a in ActionType}

_SYSTEM_PROMPT = (
    "You are a site-reliability remediation assistant. You do NOT execute "
    "anything. You only SUGGEST exactly one action from a fixed allowlist, with "
    "a confidence between 0 and 1 and a short rationale.\n"
    "You MUST choose exactly one action from this allowlist and nothing else:\n"
    f"{', '.join(sorted(_ALLOWED))}.\n"
    "If you are unsure or the situation is not clearly one of these, choose "
    "'escalate'. Respond ONLY as compact JSON with keys: action, confidence, "
    "rationale."
)


def _build_user_prompt(signal: Signal) -> str:
    """Describe the signal to the model in a compact, structured way."""
    return (
        "A monitoring signal fired:\n"
        f"- source: {signal.source}\n"
        f"- metric: {signal.metric}\n"
        f"- value: {signal.value}\n"
        f"- threshold: {signal.threshold}\n"
        f"- severity: {signal.severity.value}\n"
        f"- description: {signal.description}\n"
        "Choose one allowlist action."
    )


def _parse(text: str, signal: Signal) -> Diagnosis:
    """
    Turn the model's text into a Diagnosis, trusting nothing.

    Strategy: try JSON first; whatever we get, validate the action against the
    allowlist by exact token match. If the action is missing or off-allowlist,
    fall back to ESCALATE with low confidence -- the fail-safe.
    """
    action_raw = ""
    confidence = 0.0
    rationale = ""

    # 1) Best effort: parse JSON if the model obeyed the format.
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            action_raw = str(data.get("action", "")).strip().lower()
            rationale = str(data.get("rationale", "")).strip()
            try:
                confidence = float(data.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
    except (json.JSONDecodeError, TypeError):
        pass

    # 2) Fallback: if JSON failed, scan the raw text for a known action token.
    if action_raw not in _ALLOWED:
        found = [a for a in _ALLOWED if re.search(rf"\b{re.escape(a)}\b", text.lower())]
        # Only accept if the model named exactly one allowlist action unambiguously.
        action_raw = found[0] if len(found) == 1 else ""

    # 3) Validate against the allowlist. Off-allowlist or missing -> ESCALATE.
    if action_raw not in _ALLOWED:
        return Diagnosis(
            proposed_action=ActionType.ESCALATE,
            confidence=0.30,
            rationale=(
                "LLM response did not yield a single valid allowlist action; "
                "escalating (fail-safe). raw=" + (text[:160] if text else "")
            ),
            target=signal.source,
        )

    return Diagnosis(
        proposed_action=ActionType(action_raw),
        confidence=max(0.0, min(1.0, confidence)),
        rationale=rationale or "LLM-proposed action",
        target=signal.source,
    )


class LLMDiagnoser:
    """LLM-backed Diagnoser. Satisfies the Diagnoser port structurally."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def diagnose(self, signal: Signal) -> Diagnosis:
        text = self._client.complete(_SYSTEM_PROMPT, _build_user_prompt(signal))
        return _parse(text, signal)
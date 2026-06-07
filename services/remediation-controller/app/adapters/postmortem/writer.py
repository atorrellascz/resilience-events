"""
PostMortemWriter adapters -- always runs at the end of the loop.

A first-draft incident report is ALWAYS generated for the engineering team to
review. Two implementations:

  - TemplatePostMortemWriter: deterministic, no LLM. Builds the report from the
    incident's audit trail and replay result. Zero cost, perfect for tests/demos
    and as a fallback.
  - LLMPostMortemWriter: uses the same LLMClient abstraction as the diagnoser to
    draft a prose summary. The structured facts (timeline, data recovery) are
    still computed deterministically from the incident -- the LLM only writes the
    human-readable narrative, so it can never misreport the numbers.
"""

from __future__ import annotations

from app.adapters.diagnosers.llm_client import LLMClient
from app.core.models import Incident, Outcome, PostMortem


def _timeline(incident: Incident) -> tuple[str, ...]:
    return tuple(f"{e.stage}: {e.message}" for e in incident.audit_trail)


def _data_recovery(incident: Incident) -> str:
    r = incident.replay_result
    if r is None:
        return "no replay performed"
    status = "complete" if r.complete else "PARTIAL"
    return f"{r.succeeded}/{r.attempted} requests recovered ({status})"


def _facts(incident: Incident) -> str:
    sig = incident.signal
    action = incident.diagnosis.proposed_action.value if incident.diagnosis else "none"
    return (
        f"service={sig.source} metric={sig.metric} value={sig.value:.3f} "
        f"threshold={sig.threshold:.3f} severity={sig.severity.value} "
        f"outcome={incident.outcome.value} action={action} "
        f"data_recovery=({_data_recovery(incident)})"
    )


class TemplatePostMortemWriter:
    """Deterministic post-mortem from the incident's own record."""

    def write(self, incident: Incident) -> PostMortem:
        escalated = incident.outcome is Outcome.ESCALATED
        sig = incident.signal
        summary = (
            f"Incident on {sig.source}: {sig.description or sig.metric}. "
            f"Outcome: {incident.outcome.value}. "
            f"Data recovery: {_data_recovery(incident)}."
        )
        return PostMortem(
            summary=summary,
            timeline=_timeline(incident),
            data_recovery=_data_recovery(incident),
            escalated=escalated,
        )


class LLMPostMortemWriter:
    """
    LLM drafts the narrative; the facts are computed, not trusted to the model.
    Falls back to the template wording if the LLM call yields nothing usable.
    """

    _SYSTEM = (
        "You are an SRE writing the first draft of a blameless incident "
        "post-mortem. Be concise and factual. Do not invent numbers; use only "
        "the facts provided. Output a short prose summary (3-5 sentences)."
    )

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def write(self, incident: Incident) -> PostMortem:
        escalated = incident.outcome is Outcome.ESCALATED
        facts = _facts(incident)
        try:
            summary = self._client.complete(self._SYSTEM, f"Facts:\n{facts}\n\nWrite the summary.").strip()
        except Exception:
            summary = ""
        if not summary:
            summary = (
                f"Incident on {incident.signal.source}. Outcome: "
                f"{incident.outcome.value}. Data recovery: {_data_recovery(incident)}."
            )
        return PostMortem(
            summary=summary,
            timeline=_timeline(incident),
            data_recovery=_data_recovery(incident),
            escalated=escalated,
        )

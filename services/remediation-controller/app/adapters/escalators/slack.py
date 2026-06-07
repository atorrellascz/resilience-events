"""
Escalator adapters -- ESCALATE (hand off to a human).

Escalation reuses the SAME alerting channel as the rest of the platform: Slack
via Alertmanager. Rather than calling Slack directly, the controller pushes an
alert into Alertmanager so escalations flow through the existing routing,
grouping, and silencing -- one alerting path for the whole system.

The HTTP POST is isolated behind a `send_fn` seam so the formatting logic is
testable without a network. A RecordingEscalator (in tests/fakes) is used in the
engine tests; here we provide the real-shaped adapter and a console fallback.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.models import Incident

# Given a structured alert payload (dict), deliver it. Returns nothing.
SendFn = Callable[[dict], None]


def _build_alert(incident: Incident, reason: str) -> dict:
    """Shape an Alertmanager v2 alert from the incident. One alert, labelled."""
    sig = incident.signal
    action = incident.diagnosis.proposed_action.value if incident.diagnosis else "n/a"
    return {
        "labels": {
            "alertname": "RemediationEscalation",
            "service": sig.source,
            "severity": sig.severity.value,
            "incident_id": incident.id,
            "proposed_action": action,
        },
        "annotations": {
            "summary": f"Remediation escalated for {sig.source}",
            "reason": reason,
            "signal": f"{sig.metric}={sig.value:.3f} (threshold {sig.threshold:.3f})",
        },
    }


class AlertmanagerEscalator:
    """Pushes an escalation alert into Alertmanager (same channel as system alerts)."""

    def __init__(self, send_fn: SendFn) -> None:
        self._send = send_fn

    def escalate(self, incident: Incident, reason: str) -> None:
        # send_fn would POST to http://alertmanager:9093/api/v2/alerts later.
        self._send(_build_alert(incident, reason))


class ConsoleEscalator:
    """Prints the escalation. A safe default for local runs."""

    def escalate(self, incident: Incident, reason: str) -> None:
        print(f"[ESCALATE] {incident.signal.source}: {reason} (incident {incident.id})")

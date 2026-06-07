"""
IncidentStore adapters -- the loop's memory (persistence).

In production this is split by lifecycle: Redis for active incidents (fast,
ephemeral, plus the replay queue and cooldowns) and MongoDB for closed incidents
and post-mortems (durable, queryable history). The core only sees the
IncidentStore interface; the split is an adapter concern.

Here we provide the in-memory store used everywhere today. The Redis/Mongo
adapters will implement the same two methods.
"""

from __future__ import annotations

from app.core.models import Incident


class InMemoryIncidentStore:
    """Keeps incidents in a dict. Deterministic, dependency-free."""

    def __init__(self) -> None:
        self._store: dict[str, Incident] = {}

    def save(self, incident: Incident) -> None:
        self._store[incident.id] = incident

    def get(self, incident_id: str) -> Incident | None:
        return self._store.get(incident_id)

    def all(self) -> list[Incident]:
        """Convenience for inspection/demos (not part of the port)."""
        return list(self._store.values())

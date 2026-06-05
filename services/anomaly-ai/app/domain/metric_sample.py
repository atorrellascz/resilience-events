from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


# Valid sample kinds/states — domain rule.
_VALID_KINDS = {"latency", "error_rate", "cpu", "memory", "custom"}


@dataclass
class MetricSample:
    """An operational metric sample — the central entity of the domain.

    Pure Python: it knows NOTHING about SQLAlchemy or HTTP. Validation lives in the factory.
    """
    service: str
    kind: str
    value: float
    id: str = field(default_factory=lambda: str(uuid4()))
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def create(service: str, kind: str, value: float) -> "MetricSample":
        """Factory: the only way to create a valid sample (invariants protected)."""
        if not service or not service.strip():
            raise ValueError("service is required")
        normalized_kind = kind.strip().lower() if kind else ""
        if normalized_kind not in _VALID_KINDS:
            normalized_kind = "custom"  # safe default
        return MetricSample(
            service=service.strip(),
            kind=normalized_kind,
            value=float(value),
        )
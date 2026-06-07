"""
Actuator adapters -- Stage 4 of the loop (ACT).

The actuator is the ONLY component that changes the outside world. It maps an
allowlist action to a concrete operation (delete a pod, patch replicas) against
the Kubernetes API.

Two safety properties are non-negotiable here:
  1. DRY-RUN: when dry_run=True (the engine's default), the actuator computes
     and reports what it WOULD do, and changes nothing.
  2. NO LEAKS: it never raises past its boundary. Any failure comes back as an
     ActionResult with `error` populated, so the engine can escalate cleanly.

The actual Kubernetes calls are isolated behind a small `KubernetesOps` seam so
the mapping logic (action -> operation, dry-run handling, error capture) is fully
testable without a cluster. A FakeKubernetesOps is provided for that.
"""

from __future__ import annotations

from typing import Protocol

from app.core.models import ActionResult, ActionType, Incident


class KubernetesOps(Protocol):
    """The minimal set of cluster operations the actuator needs."""

    def delete_pod_of(self, workload: str) -> str:
        """Delete a pod of the workload (Deployment recreates it). Returns detail."""
        ...

    def scale(self, workload: str, delta: int) -> str:
        """Change replica count by delta (+/-). Returns detail."""
        ...


class FakeKubernetesOps:
    """Records operations instead of performing them. For tests/local."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def delete_pod_of(self, workload: str) -> str:
        self.calls.append(f"delete_pod:{workload}")
        return f"deleted a pod of {workload}"

    def scale(self, workload: str, delta: int) -> str:
        self.calls.append(f"scale:{workload}:{delta:+d}")
        return f"scaled {workload} by {delta:+d}"


class KubernetesActuator:
    """Executes allowlist actions against Kubernetes. Honors dry-run."""

    def __init__(self, ops: KubernetesOps, scale_step: int = 1) -> None:
        self._ops = ops
        self._scale_step = scale_step

    def execute(self, incident: Incident, dry_run: bool) -> ActionResult:
        diagnosis = incident.diagnosis
        action = diagnosis.proposed_action
        target = diagnosis.target or incident.signal.source

        # Describe the intended operation up front (used for dry-run reporting).
        intent = {
            ActionType.RESTART_POD: f"restart a pod of {target}",
            ActionType.SCALE_UP: f"scale {target} up by {self._scale_step}",
            ActionType.SCALE_DOWN: f"scale {target} down by {self._scale_step}",
        }.get(action)

        # The engine should never route NO_OP/ESCALATE here, but be defensive.
        if intent is None:
            return ActionResult(
                action=action, target=target, executed=False, dry_run=dry_run,
                detail=f"no actuator mapping for {action.value}; nothing done",
            )

        if dry_run:
            return ActionResult(
                action=action, target=target, executed=False, dry_run=True,
                detail=f"DRY-RUN: would {intent}",
            )

        # Real execution -- capture any failure as an error, never raise out.
        try:
            if action is ActionType.RESTART_POD:
                detail = self._ops.delete_pod_of(target)
            elif action is ActionType.SCALE_UP:
                detail = self._ops.scale(target, +self._scale_step)
            else:  # SCALE_DOWN
                detail = self._ops.scale(target, -self._scale_step)
            return ActionResult(
                action=action, target=target, executed=True, dry_run=False, detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 -- boundary: convert to error result
            return ActionResult(
                action=action, target=target, executed=False, dry_run=False,
                error=f"{type(exc).__name__}: {exc}",
            )

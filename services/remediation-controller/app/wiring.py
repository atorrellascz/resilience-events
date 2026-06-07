"""
Composition root -- where concrete adapters are wired into the engine.

This is the ONLY place that knows which concrete implementation backs each port.
Everything else depends on interfaces. Swapping the mock diagnoser for a real
LLM, or the in-memory store for Redis+Mongo, is a change here and nowhere else.

`build_default_engine` returns a safe, dependency-free engine (mock diagnoser,
fake k8s ops, console escalator, in-memory store, dry-run ON). That is what runs
in tests and local demos. `build_from_config` (later) will read environment/
config to select real adapters for the cluster.
"""

from __future__ import annotations

from app.adapters.actuators.kubernetes import FakeKubernetesOps, KubernetesActuator
from app.adapters.detectors.prometheus import StaticDetector
from app.adapters.diagnosers.mock import MockDiagnoser
from app.adapters.escalators.slack import ConsoleEscalator
from app.adapters.policy.gate import PolicyConfig, RiskBasedPolicyGate
from app.adapters.postmortem.writer import TemplatePostMortemWriter
from app.adapters.replayers.redpanda import NoopReplayer
from app.adapters.stores.memory import InMemoryIncidentStore
from app.adapters.verifiers.prometheus import StaticVerifier
from app.core.engine import EngineConfig, RemediationEngine
from app.core.models import Signal, Verification


def build_default_engine(
    signals: list[Signal] | None = None,
    *,
    dry_run: bool = True,
    policy_config: PolicyConfig | None = None,
    verification: Verification | None = None,
) -> RemediationEngine:
    """A fully-wired, dependency-free engine. Safe by default (dry-run ON)."""
    return RemediationEngine(
        detector=StaticDetector(signals or []),
        diagnoser=MockDiagnoser(),
        policy_gate=RiskBasedPolicyGate(policy_config),
        actuator=KubernetesActuator(FakeKubernetesOps()),
        verifier=StaticVerifier(
            verification or Verification(True, 0.0, 0.0, "static verifier")
        ),
        replayer=NoopReplayer(),
        escalator=ConsoleEscalator(),
        postmortem_writer=TemplatePostMortemWriter(),
        store=InMemoryIncidentStore(),
        config=EngineConfig(dry_run=dry_run),
    )

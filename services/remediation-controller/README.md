# remediation-controller

The guardrailed AI remediation loop — the "brain" that consumes anomaly signals
and drives an incident to resolution **or safely hands it to a human**. This is
the centerpiece of the platform's data-resilience story.

> **Status:** loop + all adapters complete, **40 tests passing**. Runs end to end
> in memory today (dry-run safe by default). What remains is *wiring to live
> infrastructure* (real LLM SDKs, Prometheus, Kubernetes, Redpanda, Redis,
> MongoDB) — not new logic. See the roadmap at the bottom.

---

## What it does

When something goes wrong, the controller runs a closed loop:

```
DETECT → DIAGNOSE → POLICY GATE → ACT → VERIFY → REPLAY → (ESCALATE)
                                                      └──────────────→ POST-MORTEM (always)
```

- **Detect** — deterministic, statistical signals (never an LLM).
- **Diagnose** — an LLM proposes ONE action from a fixed **allowlist** with a
  confidence and rationale. It only *suggests*.
- **Policy gate** — deterministic safety boundary: approve, require human
  approval, or deny.
- **Act** — perform the approved action (Kubernetes API). Dry-run by default.
- **Verify** — did the metric actually recover?
- **Replay** — *always-on after recovery*: re-process requests lost during the
  outage from a durable write-ahead-log so **no data is lost** (the "Veeam
  moment").
- **Escalate** — anything unsafe, denied, failed, or partially recovered goes to
  a human via the same Slack/Alertmanager channel the rest of the system uses.
- **Post-mortem** — a first-draft report is **always** generated for the
  engineering team to review (flagged if the incident was escalated).

## Design principles (non-negotiable)

1. **The LLM never detects and never acts.** Detection is statistical; action is
   gated and executed deterministically. The LLM only suggests from the allowlist.
2. **Closed allowlist.** The LLM cannot invent actions — enforced by the type
   system (an enum), not by hope. Off-allowlist suggestions are rejected and the
   incident is escalated.
3. **Everything is auditable.** The `Incident` is immutable; each stage appends
   to an append-only audit trail.
4. **Human-in-the-loop first.** Risky actions require approval (the "approval
   checkpoints"). Low confidence routes to a human rather than being discarded.
5. **Fail-safe.** When in doubt, escalate — never "try and see". Dry-run is the
   default; autonomy is opt-in and risk-gated.

## Architecture (hexagonal — ports & adapters)

The **core** (`app/core/`) is agnostic of infrastructure. It knows only the
domain model and the port interfaces. Concrete infrastructure is supplied by
**adapters** that implement those ports, so the core is testable in memory and
reusable across substrates. A single **composition root** (`app/wiring.py`) is
the only place that knows which concrete adapter backs each port.

```
app/
  core/
    models.py      # Incident (flows through the loop) + enums (allowlist) + payloads
    ports.py       # the 9 interfaces every stage/adapter must satisfy
    engine.py      # RemediationEngine — orchestrates the loop, agnostic of infra
  adapters/
    diagnosers/    # MockDiagnoser (hybrid rules) + LLMDiagnoser + LLMClient (OpenAI/Claude stubs)
    policy/        # RiskBasedPolicyGate (declarative config, risk levels, cooldown)
    detectors/     # PrometheusDetector (injectable query) + StaticDetector
    actuators/     # KubernetesActuator (dry-run, error capture, injectable ops)
    verifiers/     # ThresholdVerifier + StaticVerifier
    escalators/    # AlertmanagerEscalator (same channel as system alerts) + Console
    replayers/     # RedpandaReplayer (idempotent, offset-window design) + Noop
    postmortem/    # TemplatePostMortemWriter + LLMPostMortemWriter
    stores/        # InMemoryIncidentStore (Redis + Mongo adapters: pending)
  wiring.py        # composition root — wires concrete adapters into the engine
tests/
  fakes.py             # in-memory test doubles for every port
  test_engine.py       # branch coverage of the orchestration logic
  test_diagnosers.py   # mock + LLM diagnoser, incl. the allowlist guardrail tests
  test_policy.py       # every policy-gate decision rule
  test_scenarios.py    # end-to-end narratives (stuck pod + database down)
  test_integration.py  # the whole loop wired with real adapters
```

## Data & channels (how persistence and transport are split)

| Concern | Technology | Why |
|---|---|---|
| Capture for replay | **Redpanda** (write-ahead-log) | durable, ordered, exact offsets — the gateway journals each request before processing. *Not* Loki: observability can drop lines; replay needs guarantees. |
| Active incident state | **Redis** | fast, ephemeral: in-flight incidents, replay queue, cooldowns. |
| Incident history | **MongoDB** | durable, queryable: closed incidents + post-mortems for human review (documents with nested, variable shape). |

The core only sees the `IncidentStore` interface; which store is behind it is an
adapter concern. In-memory today; Redis + Mongo adapters are pending (see roadmap).

## Replay strategy (the "Veeam moment")

After recovery, replay re-applies requests lost during the outage, reading from
the gateway's write-ahead-log on Redpanda. The production design (documented in
`app/adapters/replayers/redpanda.py`) rests on three properties:

- **Incident window** — replay only the offset range `[outage_start, recovery]`;
  traffic that arrives after recovery follows the normal path and is not replayed.
- **Checkpoints** — resume from the last committed offset on retry, not from zero.
- **Idempotency** — re-applying an already-persisted request is a no-op, so retries
  and overlap with live traffic never corrupt data. Redpanda's per-partition
  ordering preserves sequence.

## Running the tests

```bash
PYTHONPATH=. python -m pytest -q     # 40 passing
```

All scenarios run on fakes/in-memory adapters — no Kubernetes, Prometheus, LLM,
Redpanda, or database needed.

## Roadmap — wiring to live infrastructure (not new logic)

- [ ] **LLM**: wire OpenAI and Claude SDKs into `LLMClient` (env-driven API keys;
      the `LLMDiagnoser` and parser already work — only the client `complete()`
      stub needs the SDK call).
- [ ] **Detector/Verifier**: point them at the real Prometheus HTTP API.
- [ ] **Actuator**: wire ops to the Python `kubernetes` client, with RBAC scoped
      strictly to the allowlist actions.
- [ ] **Replayer**: connect to the gateway's write-ahead-log topic (offset window
      + checkpoint, per the design note in the replayer module).
- [ ] **Persistence**: Redis (active state) + MongoDB (history) store adapters.
- [ ] **Deploy** as a service in the cluster; gradually raise the auto-approve
      ceiling as confidence in the loop grows.
- [ ] **edge-gateway**: add request journaling to Redpanda (the WAL the replay
      reads from) — a prerequisite for live replay.
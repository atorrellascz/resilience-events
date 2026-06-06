# Resilience Events Platform

A polyglot microservices platform built around **data resilience** — detection, recovery, and learning in one loop. It runs locally on Kubernetes with full GitOps and observability, and is designed to deploy to Azure without redesign.

> Portfolio / case-study project. The goal is production-grade engineering practices — declarative everything, no manual hacks, no secrets in Git — not feature breadth.

---

## What it is

Four services, each written in the language and backed by the datastore that best fits its job. They share a uniform operational contract (`/health`, `/ready`, `/metrics`) and emit **standardized RED metrics** regardless of language, so a single dashboard works across all of them.

| Service        | Language        | Datastore   | Role                                        |
|----------------|-----------------|-------------|---------------------------------------------|
| events-api     | .NET 10         | SQL Server  | Event ingestion (clean architecture, EF Core) |
| catalog-api    | Go              | MongoDB     | System catalog (idiomatic Go layers)        |
| anomaly-ai     | Python / FastAPI| MySQL       | Anomaly samples (async SQLAlchemy)          |
| edge-gateway   | Go              | —           | Reverse proxy / request journaling          |

"Polyglot" is deliberate: it demonstrates consistent operational standards (metrics, probes, packaging, GitOps) **across heterogeneous stacks** — the real challenge in a platform team.

---

## Architecture principles

- **GitOps as the source of truth.** The repository defines the desired state; Argo CD reconciles the cluster to it. Changes go through Git, not `kubectl`/`helm` run by hand. This kills tribal knowledge and makes the platform reproducible.
- **Same image everywhere.** Services read configuration (connection strings, etc.) from the environment, so the identical container runs locally and in the cloud. Databases are StatefulSets locally and managed services in Azure (Azure SQL, Cosmos DB, Azure Database for MySQL).
- **Clear infra/app boundary.** Terraform provisions infrastructure (AKS, Key Vault, networking) *before* the cluster exists; Argo CD manages everything *inside* the cluster (apps + observability). Neither crosses into the other's domain.
- **Immutable image tags.** Each change is a new tag (commit SHA in CI/CD), so the deployed artifact is always traceable to its source — reusing tags breaks that traceability and causes stale deploys.
- **Safety and human oversight built in, not bolted on.**

---

## Observability (three pillars)

| Pillar   | Tool          | Answers              |
|----------|---------------|----------------------|
| Metrics  | Prometheus    | *What* is wrong?     |
| Alerts   | Alertmanager  | *Does it page?*      |
| Logs     | Loki          | *Why* is it wrong?   |

- **RED dashboards** (Rate, Errors, Duration) per service, as code, auto-provisioned via the Grafana sidecar.
- **SLOs with multi-window burn-rate alerts** (availability + latency) following the Google SRE workbook; the SLI excludes operational endpoints so health checks don't pollute it.
- **Loki + Promtail** for centralized logs, correlatable with metrics in Grafana via a shared label model.
- Alerts route to **Slack** through an AlertmanagerConfig CRD, with the webhook injected from a Kubernetes Secret.

Everything in the observability stack is declarative and managed by Argo CD.

---

## Tech stack

- **Languages:** .NET 10, Go 1.26, Python 3.13
- **Datastores:** SQL Server, MongoDB, MySQL
- **Orchestration:** Kubernetes (Docker Desktop / kind locally, AKS in cloud)
- **Packaging:** Helm (per-service charts + umbrella)
- **GitOps:** Argo CD
- **Observability:** kube-prometheus-stack (Prometheus, Grafana, Alertmanager), Loki, Promtail
- **Infrastructure (planned):** Terraform → Azure
- **CI/CD (planned):** GitHub Actions (build/test/scan/push with immutable tags)

---

## Repository layout

```
services/            # The 4 microservices (source + Dockerfiles + tests)
deploy/
  helm/
    apps/            # Per-service Helm charts (Deployment, Service, ServiceMonitor)
    infra-dev/       # Local databases as StatefulSets
    platform/        # Umbrella chart (local platform)
    dashboards/      # Observability config as code (dashboards, SLO rules, datasources, Slack)
  argocd/            # Argo CD Application manifests
docs/                # SETUP, RUNBOOK, and decision records
docker-compose.yml   # Phase 0 local stack (pre-Kubernetes)
```

---

## Getting started

- **Setup / bootstrap:** see [`docs/Setup.md`](docs/Setup.md) — prerequisites, secrets, charts, and Argo CD install.
- **Run / demo:** see [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — startup, UI access, traffic generation, and a chaos-incident walkthrough.

---

## Roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| 0 | Local platform (Docker Compose) | ✅ |
| 1 | Four services, clean architecture | ✅ |
| 2 | Kubernetes + GitOps (Argo CD) | ✅ |
| 3 | Observability (metrics, alerts, logs) | ✅ |
| 4 | Guardrailed AI remediation loop + request replay + auto post-mortem | planned |
| 5 | Terraform → Azure (AKS, Key Vault, managed data services) | planned |
| 6 | CI/CD (GitHub Actions, immutable tags) | planned |
| 7 | Service mesh (Istio) + advanced chaos | planned |
| 8 | Final docs + demo script | planned |

### The AI loop (Phase 4 — the centerpiece)

A guardrailed closed loop: **detect** anomalies with deterministic statistics (never an LLM) → **diagnose** with an LLM choosing from a fixed allowlist + confidence → **policy gate** → **act** → **verify** → if unsafe or unsuccessful, **escalate to a human** via alert → **replay** lost requests (write-ahead-log, idempotent — the same recovery idea behind backup/restore) → the AI **drafts the first post-mortem** for an engineer to review. Human-in-the-loop first.

---

## Notes

This is a learning-driven project; some decisions favor clarity and reproducibility over completeness. Trade-offs and known tooling limitations are documented honestly in `docs/` rather than hidden.
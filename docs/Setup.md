# SETUP — Prerequisites & Bootstrap (Phases 0–2)

This document lists everything required to build and run the Resilience Events
platform locally, in the order it must be done. It exists so the platform can be
rebuilt from scratch by anyone (no tribal knowledge).

> **Scope:** Phase 0 (local Docker Compose), Phase 1 (real domain services),
> Phase 2 (local Kubernetes + Helm + Argo CD / GitOps).
>
> **Note on secrets:** the literal dev passwords below are **local-only**. In
> Azure they come from Key Vault and never live in git. They are shown here only
> so a local environment can be reproduced.

---

## 0. Host tooling (install once)

Installed via `winget` on Windows. Versions are the ones this project was built
and verified against.

| Tool | Version | Install |
|------|---------|---------|
| Docker Desktop | 29.5.2 | (manual install) |
| Docker Compose | v2 (`docker compose`) | bundled with Docker Desktop |
| .NET SDK | 10.0.x (LTS) | `winget install Microsoft.DotNet.SDK.10` (already had 10) |
| Go | 1.26.4 | `winget install GoLang.Go` |
| Python | 3.13.13 | `winget install Python.Python.3.13` |
| Git | 2.47.x | `winget install Git.Git` |
| kubectl | v1.34.x | bundled with Docker Desktop |
| Helm | v4.2.0 | `winget install Helm.Helm` |

After installing Go/Python, **restart the terminal (or VS Code)** so the updated
PATH is picked up.

### Docker Desktop resources
- Memory: **6–8 GB minimum** (Settings → Resources). Kubernetes + SQL Server +
  the rest will not fit in 2 GB.
- Kubernetes: Settings → Kubernetes → **Enable**, method **kind**, version
  **1.34.8** (kept within ±1 minor of the kubectl client per the version-skew
  policy) → Apply & Restart.

### ⚠️ kubectl context safety
This machine also has **production AKS contexts** (Jazz Casino). Before ANY
`kubectl`/`helm` command for this project, confirm the local context:

```powershell
kubectl config current-context        # must print: docker-desktop
kubectl config use-context docker-desktop   # if it isn't
```

Never run this project's manifests against a prod context.

---

## 1. Repository

```powershell
cd C:\Veeam\resilience-events
git init -b main
# .gitignore is committed FIRST, before any `git add .`, so secrets never enter git.
git add .gitignore
git commit -m "chore: add .gitignore (secrets never in git)"
```

Public repo: `https://github.com/atorrellascz/resilience-events`

---

## 2. Local secrets file (`.env`) — Phase 0/1 (Docker Compose)

`.env` is git-ignored. Create it in the repo root with the local dev passwords:

```dotenv
MSSQL_SA_PASSWORD=Resilience!Dev2026
MYSQL_ROOT_PASSWORD=Resilience!Root2026
MYSQL_PASSWORD=Resilience!App2026
```

> MongoDB intentionally has **no auth in local** (it is isolated on the internal
> Docker network). In Azure it becomes Cosmos DB (Mongo API) with credentials
> from Key Vault. That's why there is no Mongo entry here.

---

## 3. Phase 0 / 1 — run on Docker Compose

Build + run. Two profiles exist: `core` (gateway, events-api, sqlserver, redis,
prometheus, grafana) and `full` (adds catalog-api, anomaly-ai, mongodb, mysql,
redpanda, loki).

```powershell
docker compose --profile full up -d --build
docker compose ps                  # all services healthy / running
```

Verify endpoints (each service exposes `/`, `/health`, `/ready`, `/metrics`):

```powershell
docker compose exec events-api  wget -qO- http://localhost:8080/api/events
docker compose exec catalog-api wget -qO- http://localhost:8080/api/systems
# anomaly-ai image has no wget; use python:
docker compose exec anomaly-ai python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/api/samples').read().decode())"
```

UIs: Prometheus `http://localhost:9090/targets`, Grafana `http://localhost:3000`.

### Per-service build gotchas resolved in Phase 1 (already fixed in the code)
- **catalog-api (Go + Mongo):** needs `go.sum` — run `go mod tidy` in
  `services/catalog-api`; Dockerfile copies `go.mod go.sum`.
- **anomaly-ai (Python + MySQL):** `requirements.txt` must include
  `cryptography` (MySQL 8 `caching_sha2_password` auth) and must **not** set
  `pool_pre_ping=True` (bug with the aiomysql async adapter). `DATABASE_URL`
  comes from env; the app fails fast if it is missing.

### Stop compose (frees RAM once you move to Kubernetes)
```powershell
docker compose --profile full down      # add -v to also drop DB volumes
```

---

## 4. Phase 2 — Kubernetes (local kind via Docker Desktop)

> Docker Desktop **shares its image registry** with its Kubernetes, so locally
> built images (`rep/events-api:0.1.0`, etc.) are usable by k8s directly — no
> `kind load` needed. After rebuilding an image, force a rollout:
> `kubectl rollout restart deployment <name>`.

### 4a. Build the images (compose is used only as the build recipe)
```powershell
docker compose build      # builds rep/events-api, rep/catalog-api, rep/anomaly-ai, rep/edge-gateway
```

### 4b. Create the Kubernetes Secrets (NOT in git, created manually in local)
Confirm context is `docker-desktop` first.

```powershell
# events-api + sqlserver share this one. 'sql-connection' holds the FULL connection
# string (avoids fragile $(VAR) interpolation inside the manifest).
kubectl create secret generic events-api-secrets `
  --from-literal=sa-password='Resilience!Dev2026' `
  --from-literal=sql-connection='Server=sqlserver,1433;Database=events;User Id=sa;Password=Resilience!Dev2026;TrustServerCertificate=True'

# mysql + anomaly-ai. 'db-url' holds the full SQLAlchemy async URL.
kubectl create secret generic mysql-secrets `
  --from-literal=root-password='Resilience!Root2026' `
  --from-literal=app-password='Resilience!App2026' `
  --from-literal=db-url='mysql+aiomysql://anomaly:Resilience!App2026@mysql:3306/anomaly'
```

> In Azure these Secrets are populated from Key Vault (e.g. via External Secrets),
> not created by hand.

### 4c. Chart layout
```
deploy/helm/
├── apps/         events-api, catalog-api, anomaly-ai, edge-gateway   (run in local AND Azure)
├── infra-dev/    sqlserver-dev, mongodb-dev, mysql-dev               (StatefulSets, LOCAL ONLY)
└── platform/     umbrella chart that depends on all of the above
```
> infra-dev charts are **local only**. In Azure, Terraform provisions managed
> services (Azure SQL, Cosmos DB, Azure Database for MySQL) instead.

### 4d. Resolve umbrella dependencies
```powershell
helm dependency build ./deploy/helm/platform
helm template platform ./deploy/helm/platform   # optional: validate it renders
```
Generated artifacts are git-ignored:
```
deploy/helm/platform/charts/
deploy/helm/platform/Chart.lock
```

### 4e. Install Argo CD (GitOps controller) into the cluster
```powershell
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl get pods -n argocd -w        # wait until all ~7 pods are Running
```

Get the initial admin password and open the UI:
```powershell
$pwd = kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}"
[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($pwd))
# UI: port-forward, then browse https://localhost:8090  (user: admin)
kubectl port-forward -n argocd svc/argocd-server 8090:443
```

### 4f. Point Argo CD at the repo (the GitOps Application)
The Application manifest is versioned at `deploy/argocd/platform-app.yaml`
(repo `…/resilience-events`, path `deploy/helm/platform`, `prune: true`,
`selfHeal: true`). Apply it once:

```powershell
kubectl apply -f deploy/argocd/platform-app.yaml
```

From here on, **the repo is the source of truth.** Argo syncs the cluster to git,
reverts manual drift (selfHeal), and prunes deleted resources. To change the
platform: commit + push — do not `kubectl`/`helm` by hand.

Verify:
```powershell
kubectl get pods      # 4 apps + 3 DB StatefulSets, all 1/1
# Argo UI shows: Synced / Healthy
```

---

## Open items (tech debt, non-blocking)
- **catalog-api** returns `null` instead of `[]` for an empty list (Go Mongo
  driver `cursor.All` behavior). Real fix: force `[]` in the handler layer.
  Cosmetic.
- Phase 1 polish deferred: unit tests for catalog-api & anomaly-ai;
  OpenTelemetry on all three services.
- Reusing image tag `0.1.0` for changed code is an anti-pattern (k8s can't tell
  it changed → manual `rollout restart`). CI/CD will use immutable tags per commit.

## Architecture Decision Records to write (`docs/DECISIONS.md`)
Fluent API vs Data Annotations · Redpanda→Event Hubs · migrate-on-startup with
retry vs Job · core/full profiles · DTOs vs entity · domain entity vs ORM model ·
removed `pool_pre_ping` · Mongo no-auth in local · all-in-`default`-namespace in
local (separate by domain in prod).

## Observability stack (Phase 3)

The observability stack is deployed declaratively via Argo CD. These are the bootstrap notes.

### Components

| Argo Application | Source | Namespace |
|------------------|--------|-----------|
| observability | `prometheus-community/kube-prometheus-stack` v86.2.0 | monitoring |
| dashboards | `deploy/helm/dashboards` (in this repo) | monitoring |
| loki | `grafana/loki` v6.24.0 (single-binary mode) | monitoring |
| promtail | `grafana/promtail` v6.16.6 (DaemonSet) | monitoring |

The `dashboards` chart bundles all observability *config as code*: the RED dashboard (ConfigMap with `grafana_dashboard: "1"`), the Loki datasource (ConfigMap with `grafana_datasource: "1"`), the SLO `PrometheusRule`, and the Slack `AlertmanagerConfig`. The Grafana sidecars auto-discover the dashboard and datasource by label.

### Apply the Argo Applications

```powershell
kubectl apply -f deploy/argocd/observability-app.yaml
kubectl apply -f deploy/argocd/dashboards-app.yaml
kubectl apply -f deploy/argocd/loki-app.yaml
kubectl apply -f deploy/argocd/promtail-app.yaml
```

Argo reconciles each to its source. Verify:

```powershell
kubectl get applications -n argocd
kubectl get pods -n monitoring
```

### Slack alerting — secret + bootstrap

1. Create a Slack Incoming Webhook (https://api.slack.com/apps → your app → Incoming Webhooks) and store it as a Secret (never in Git):

```powershell
kubectl create secret generic alertmanager-slack -n monitoring --from-literal=webhook-url='YOUR_WEBHOOK_URL'
```

2. The kube-prometheus-stack v86.2.0 does **not** propagate `alertmanagerConfigMatcherStrategy` via Helm values. Apply once after deploy so alerts from services in `default` reach the Slack receiver (which lives in `monitoring`):

```powershell
@'
spec:
  alertmanagerConfigMatcherStrategy:
    type: None
'@ | Out-File -Encoding ascii patch.yaml
kubectl patch alertmanager kube-prometheus-stack-alertmanager -n monitoring --type merge --patch-file patch.yaml
Remove-Item patch.yaml
```

> This is a documented limitation of the chart version, applied as an explicit bootstrap step rather than hidden. The intent is also declared in `observability-app.yaml` for when the chart supports it.

### Resource notes (local)

- The full stack needs node memory headroom. Raise WSL memory (`%USERPROFILE%\.wslconfig` → `[wsl2] memory=12GB`), then `wsl --shutdown` and restart Docker Desktop.
- Disable "Resource Saver" in Docker Desktop — it throttles pods on idle and causes restarts.
- Grafana memory limit is set to 512Mi (256Mi caused `OOMKilled`).
- Loki runs in single-binary mode with filesystem storage and caching disabled to stay light locally; in the cloud it would use object storage (Azure Blob) and a scalable deployment mode.
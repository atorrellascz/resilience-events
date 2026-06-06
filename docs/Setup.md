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
| .NET SDK | 10.0.x (LTS) | `winget install Microsoft.DotNet.SDK.8` (already had 10) |
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

## Post-deploy: enrutado cross-namespace de Alertmanager

El chart kube-prometheus-stack v86.2.0 no propaga `alertmanagerConfigMatcherStrategy`
via Helm values. Tras el primer deploy, aplicar una vez:

    kubectl patch alertmanager kube-prometheus-stack-alertmanager -n monitoring \
      --type merge -p '{"spec":{"alertmanagerConfigMatcherStrategy":{"type":"None"}}}'

Esto permite que las alertas de servicios en otros namespaces (ej. events-api en
`default`) lleguen a los receivers del AlertmanagerConfig (que vive en `monitoring`).
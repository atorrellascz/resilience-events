# RUNBOOK — Resilience Events Platform

Operational guide to start, access, and demo the platform on a **local Kubernetes** cluster (Docker Desktop / kind). Everything is managed declaratively via Argo CD (GitOps); this runbook covers the operational steps to run and demonstrate it.

> **Context safety:** every `kubectl` command targets the local cluster. Before running anything destructive (scaling, deleting), confirm the context:
> ```powershell
> kubectl config current-context   # must be: docker-desktop
> ```

---

## 1. Prerequisites

- Docker Desktop with Kubernetes enabled (WSL2 backend on Windows).
- WSL memory raised to at least 8–12 GB (`%USERPROFILE%\.wslconfig` → `[wsl2] memory=12GB`), then `wsl --shutdown` and restart Docker Desktop. The full observability stack needs the headroom.
- "Resource Saver" disabled in Docker Desktop (it throttles pods on idle).
- `kubectl`, `helm`, and the Argo CD CLI (optional) installed.
- Argo CD installed in the `argocd` namespace (see `docs/Setup.md` for bootstrap).

---

## 2. Bring the platform up

The cluster converges to Git automatically through Argo CD. After a fresh start, the Argo Applications reconcile the desired state.

### 2.1 Verify Argo Applications

```powershell
kubectl get applications -n argocd
```

Expected (all `Synced` / `Healthy`):

| Application          | What it manages                                        |
|----------------------|--------------------------------------------------------|
| resilience-platform  | The 4 services + 3 databases (umbrella chart)          |
| observability        | kube-prometheus-stack (Prometheus, Grafana, Alertmanager) |
| dashboards           | RED dashboard, Loki datasource, SLO rules, Slack config |
| loki                 | Loki (single-binary) for centralized logs              |
| promtail             | Promtail DaemonSet shipping pod logs to Loki           |

### 2.2 Verify workloads

```powershell
kubectl get pods                  # 4 services + 3 DBs in default
kubectl get pods -n monitoring    # observability stack + loki + promtail
```

All pods should reach `Running` with their full readiness (e.g. Prometheus `2/2`, Grafana `3/3`).

### 2.3 One-time bootstrap (post-deploy)

The kube-prometheus-stack v86.2.0 does not propagate `alertmanagerConfigMatcherStrategy` via Helm values. Apply once so alerts from services in `default` reach the Slack receiver defined in `monitoring`:

```powershell
@'
spec:
  alertmanagerConfigMatcherStrategy:
    type: None
'@ | Out-File -Encoding ascii patch.yaml
kubectl patch alertmanager kube-prometheus-stack-alertmanager -n monitoring --type merge --patch-file patch.yaml
Remove-Item patch.yaml
```

Also create the Slack webhook secret (replace with your webhook URL):

```powershell
kubectl create secret generic alertmanager-slack -n monitoring --from-literal=webhook-url='YOUR_WEBHOOK_URL'
```

---

## 3. Access the UIs (port-forwards)

Each UI is reached via `kubectl port-forward`. Run each in its own terminal and keep it open.

### Argo CD
```powershell
kubectl port-forward -n argocd svc/argocd-server 8090:443
```
→ https://localhost:8090 — initial admin password:
```powershell
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}"
# decode the base64 value
```

### Grafana (dashboards + logs)
```powershell
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3001:80
```
→ http://localhost:3001 — login `admin` / `admin`.
- **Dashboards** → "Resilience Events — RED" (switch services with the `Service (job)` selector).
- **Explore** → datasource **Loki** → query `{namespace="default"}` for logs.

### Prometheus (metrics + alerts)
```powershell
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9091:9090
```
→ http://localhost:9091 — `Status → Target health` (scrape targets), `Alerts` (SLO alerts).

### Alertmanager (routing)
```powershell
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093
```
→ http://localhost:9093 — `Status` shows the loaded config (Slack receiver).

### A service directly (for traffic)
```powershell
kubectl port-forward svc/events-api 8080:8080
```

---

## 4. Generate traffic

The RED dashboards and SLI need traffic to show data. With the events-api port-forward running on 8080:

### Steady traffic (let it run)
```powershell
while ($true) {
  try { Invoke-RestMethod http://localhost:8080/api/events -TimeoutSec 3 | Out-Null } catch {}
  Start-Sleep -Milliseconds 200
}
```

### Fixed burst
```powershell
1..400 | ForEach-Object {
  try { Invoke-RestMethod http://localhost:8080/api/events -TimeoutSec 2 | Out-Null } catch {}
  try { Invoke-RestMethod http://localhost:8080/health -TimeoutSec 2 | Out-Null } catch {}
  Start-Sleep -Milliseconds 200
}
```

> Other services: `catalog-api` (`/api/systems`, port-forward 8082), `anomaly-ai` (`/api/samples`, 8083), `edge-gateway` (`/`, 8080). Each exposes the same `/health`, `/ready`, `/metrics` contract.

Watch the dashboard (Grafana, auto-refresh 5–10s) — Rate, Errors, and Duration panels should move.

---

## 5. Incident demo (chaos: database down)

Simulates a critical dependency failure to show detection across the whole observability stack.

### 5.1 Prepare observation
- Grafana → "Resilience Events — RED" dashboard, `events-api` selected, auto-refresh on.
- Prometheus → `Alerts` tab.
- Grafana → Explore → Loki (to read the error logs live).
- Keep steady traffic running (section 4).

### 5.2 Pause Argo self-heal
So the database stays down (otherwise Argo revives it):

```powershell
@'
spec:
  syncPolicy:
    automated: null
'@ | Out-File -Encoding ascii pause.yaml
kubectl patch application resilience-platform -n argocd --type merge --patch-file pause.yaml
Remove-Item pause.yaml
```

### 5.3 Take the database down
```powershell
kubectl scale statefulset sqlserver --replicas=0
```

### 5.4 Observe the incident
- **Dashboard:** Error Rate panel turns red; `503` series grows; p99 latency spikes (requests hang waiting on the dead DB).
- **Readiness:** events-api `/ready` returns 503 — Kubernetes pulls the pod from balancing but does NOT kill it (liveness ≠ readiness by design).
- **Prometheus:** `job:http_error_ratio:rate5m` rises; the SLO alert moves Inactive → Pending → Firing.
- **Loki:** `{app="events-api"}` shows the DB connection errors in real time — the "why" behind the metric spike.

> **Demo note on alerts:** the real burn-rate alert (14.4× over both 5m and 1h windows) is intentionally hard to trigger with a short incident — that is its purpose (it avoids alert fatigue). To force a Firing alert in a live demo, temporarily lower the threshold (e.g. `job:http_error_ratio:rate5m > 0.05`, `for: 30s`) in `events-api-slo-rules.yaml`, commit, and let Argo sync. Restore the real threshold afterwards.

### 5.5 Restore
```powershell
kubectl scale statefulset sqlserver --replicas=1
```
Re-enable Argo self-heal (UI → resilience-platform → enable AUTO-SYNC + SELF HEAL, or re-apply the Application from Git). When the DB recovers, a "resolved" notification is sent to Slack (`send_resolved: true`).

---

## 6. Verify Slack routing (without a real incident)

Inject a test alert directly into Alertmanager (port-forward on 9093). The label `service="events-api"` matches the route to Slack:

```powershell
$body = '[{"labels":{"alertname":"TestSlack","service":"events-api","severity":"critical"},"annotations":{"summary":"Slack test","description":"If you see this in Slack, the webhook works"},"endsAt":"2026-12-31T23:59:00.000Z"}]'
Invoke-RestMethod -Method Post -Uri http://localhost:9093/api/v2/alerts -Body $body -ContentType 'application/json'
```

Wait ~30s (group_wait) → the message lands in the `#alerts` channel.

---

## 7. Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Pods stuck `ContainerCreating` / restarting | Node out of memory (limits over 100%) | Raise WSL memory in `.wslconfig`, `wsl --shutdown`, restart Docker Desktop |
| Grafana `OOMKilled` (Exit 137) | Memory limit too low | Raise `grafana.resources.limits.memory` in `observability-app.yaml` |
| Code change not reflected in pod | Reused image tag / Docker cache | Use a new immutable tag, rebuild, update `values.yaml`, push (Argo applies) |
| `helm upgrade` reverted | Argo self-heal converges to Git | Change via Git commit, not local `helm upgrade` |
| Alert never reaches Slack | `alertmanagerConfigMatcherStrategy` not set | Apply the bootstrap patch (section 2.3) |
| Loki query returns nothing for `{service=...}` | Promtail uses different labels | Use `{app="events-api"}` or `{namespace="default"}` |

---

## 8. Tear down (optional)

```powershell
# Scale services down without deleting (keeps data in PVCs)
kubectl scale deployment --all --replicas=0

# Or remove an Argo Application (and its workloads)
kubectl delete application <name> -n argocd
```
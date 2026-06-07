"""
remediation-controller -- service entrypoint.

Exposes the platform's uniform operational contract (/health, /ready, /metrics)
like the other services, and runs the remediation loop on a periodic background
task.

Today it runs with the SAFE default wiring (mock diagnoser, in-memory store,
fake Kubernetes ops) and dry_run=ON: the loop executes on a timer and produces
fully-audited incidents, but performs NO real actions. This makes the service
observable and demonstrable in the cluster while the live-infrastructure
adapters (Prometheus, Kubernetes, LLM, Redpanda, Redis, Mongo) are wired in.
Autonomy is raised later by swapping adapters and turning dry_run off via env --
no change to the loop itself.
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.core.models import Severity, Signal
from app.wiring import build_default_engine

# ── Config (same code local and prod; behavior driven by env) ──
LOOP_INTERVAL_SECONDS = float(os.getenv("REMEDIATION_LOOP_INTERVAL", "30"))
# Safe by default: real autonomy is opt-in once adapters are wired.
DRY_RUN = os.getenv("REMEDIATION_DRY_RUN", "true").lower() != "false"


def _demo_signals() -> list[Signal]:
    """
    Placeholder detector input until the Prometheus/Redpanda detector is wired.
    Returns a single benign self-check signal so the loop has something to
    process and the metrics move, without implying a real incident.
    """
    return [
        Signal(
            source="self-check", metric="loop_heartbeat", value=0.0, threshold=1.0,
            severity=Severity.INFO, description="periodic dry-run self-check",
        )
    ]


async def _run_loop() -> None:
    """Background task: run the remediation loop on a fixed interval."""
    LOOP_UP.set(1)
    try:
        while True:
            engine = build_default_engine(_demo_signals(), dry_run=DRY_RUN)
            for incident in engine.run_once():
                LOOP_RUNS.inc()
                INCIDENTS.labels(outcome=incident.outcome.value).inc()
            await asyncio.sleep(LOOP_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        LOOP_UP.set(0)
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup: launch the background remediation loop. On shutdown: cancel it.
    task = asyncio.create_task(_run_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="remediation-controller", version="0.1.0", lifespan=lifespan)

# ── Métricas RED, con los MISMOS nombres que el resto de servicios ──
HTTP_REQUESTS = Counter(
    "http_requests_received_total",
    "Total HTTP requests received.",
    ["code", "method", "endpoint"],
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["code", "method", "endpoint"],
)

# ── Métricas propias del lazo (el controlador observándose a sí mismo) ──
LOOP_RUNS = Counter("remediation_loop_runs_total", "Number of loop cycles executed.")
INCIDENTS = Counter(
    "remediation_incidents_total", "Incidents processed, by outcome.", ["outcome"]
)
LOOP_UP = Gauge("remediation_loop_up", "1 if the background loop is running.")


@app.middleware("http")
async def record_metrics(request: Request, call_next):
    # No medimos /metrics a sí mismo (ruido).
    if request.url.path == "/metrics":
        return await call_next(request)

    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start

    labels = {
        "code": str(response.status_code),
        "method": request.method,
        "endpoint": request.url.path,
    }
    HTTP_REQUESTS.labels(**labels).inc()
    HTTP_DURATION.labels(**labels).observe(elapsed)
    return response


@app.get("/health")  # liveness
async def health():
    return {"status": "healthy"}


@app.get("/ready")  # readiness — the loop task is the dependency here
async def ready():
    if LOOP_UP._value.get() != 1:  # background loop not running
        return Response(content='{"status":"not-ready"}', status_code=503,
                        media_type="application/json")
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
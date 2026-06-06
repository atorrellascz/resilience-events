import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, Request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from app.db import engine, Base
from app.repository import models  # noqa: F401 — registers the model in Base.metadata
from app.api.routes import router as samples_router
from app.repository.sample_repository import SampleRepository
from app.db import AsyncSessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup: create the table if it doesn't exist (dev). In prod: Alembic.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="anomaly-ai", version="0.1.0", lifespan=lifespan)

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

app.include_router(samples_router)


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


@app.get("/ready")  # REAL readiness — checks MySQL
async def ready():
    async with AsyncSessionLocal() as session:
        ok = await SampleRepository(session).ping()
    if not ok:
        return Response(content='{"status":"not-ready"}', status_code=503,
                        media_type="application/json")
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
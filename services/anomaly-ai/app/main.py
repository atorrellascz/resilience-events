from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from app.db import engine, Base
from app.repository import models  # noqa: F401 — registers the model in Base.metadata
from app.api.routes import router as samples_router
from app.repository.sample_repository import SampleRepository
from app.db import AsyncSessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup: create the table if it doesn't exist (dev). In prod this would be Alembic (migrations).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # On shutdown: close the engine cleanly.
    await engine.dispose()


app = FastAPI(title="anomaly-ai", version="0.1.0", lifespan=lifespan)

REQUESTS = Counter("anomaly_requests_total", "Total HTTP requests handled")

app.include_router(samples_router)


@app.middleware("http")
async def count_requests(request, call_next):
    REQUESTS.inc()
    return await call_next(request)


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
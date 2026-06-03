from fastapi import FastAPI, Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

# Phase 0: stub. Phase 4 adds: statistical detector (EWMA/z-score/IsolationForest),
# remediation controller (policy gate + actuator), and the LLM adapter (mock/Azure).
app = FastAPI(title="anomaly-ai", version="0.1.0")

# Request counter (the library handles the Prometheus format correctly).
REQUESTS = Counter("anomaly_requests_total", "Total HTTP requests handled")


@app.get("/")
def root():
    REQUESTS.inc()
    return {
        "service": "anomaly-ai",
        "language": "Python / FastAPI",
        "domain": "metric samples + AI anomaly detection & remediation",
        "message": "Hello from anomaly-ai - Phase 0 stub",
    }


@app.get("/health")  # liveness
def health():
    return {"status": "healthy"}


@app.get("/ready")  # readiness — Phase 1 checks MySQL; Phase 4 also checks Redis and the LLM
def ready():
    return {"status": "ready"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
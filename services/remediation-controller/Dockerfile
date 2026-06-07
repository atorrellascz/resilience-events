# ── runtime stage (Python needs no prior compilation like .NET/Go) ──
FROM python:3.13-slim AS final
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -u 10001 -m appuser            # non-root user (Debian slim uses useradd)
USER appuser
EXPOSE 8080
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
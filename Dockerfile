# Build from repo root: docker compose build
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gcp_secrets.py .
COPY scripts/gcp/gcs_data_sync.py scripts/gcp/gcs_data_sync.py
COPY docker/entrypoint-gcp.sh /entrypoint-gcp.sh
RUN chmod +x /entrypoint-gcp.sh
COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV GCP_SECRET_PREFIX=ikr-
ENV USE_SECRET_MANAGER=1

EXPOSE 18501

ENTRYPOINT ["/entrypoint-gcp.sh"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python scripts/health_check.py

CMD ["streamlit", "run", "streamlit_app/app.py", \
     "--server.port=18501", "--server.address=0.0.0.0", \
     "--server.headless=true"]

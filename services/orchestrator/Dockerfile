# orchestrator image. Build context is the repo root (HealthLink/).
#   docker build -f services/orchestrator/Dockerfile -t orchestrator .
FROM python:3.11-slim

WORKDIR /app

COPY services/orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY services/orchestrator/ ./

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]

# summary-agent image. Build context is the repo root (HealthLink/).
#   docker build -f services/summary_agent/Dockerfile -t summary-agent .
FROM python:3.11-slim

WORKDIR /app

COPY services/summary_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY services/summary_agent/ ./

EXPOSE 8013

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8013"]

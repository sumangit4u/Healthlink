# scheduling-agent image. Build context is the repo root (HealthLink/).
#   docker build -f services/scheduling_agent/Dockerfile -t scheduling-agent .
FROM python:3.11-slim

WORKDIR /app

COPY services/scheduling_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY services/scheduling_agent/ ./

EXPOSE 8012

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8012"]

# symptom-agent image. Build context is the repo root (HealthLink/) so the
# shared/ contract package can be copied in alongside the service code.
#   docker build -f services/symptom_agent/Dockerfile -t symptom-agent .
FROM python:3.11-slim

WORKDIR /app

COPY services/symptom_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY services/symptom_agent/ ./

EXPOSE 8010

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]

# doctor-agent image. Build context is the repo root (HealthLink/).
#   docker build -f services/doctor_agent/Dockerfile -t doctor-agent .
FROM python:3.11-slim

WORKDIR /app

COPY services/doctor_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY services/doctor_agent/ ./

# /app/data holds the bundled doctors.csv (baked into the image).
# /app/dbdata holds the SQLite file; mounted as a named volume in compose so a
# volume never shadows the CSV.
RUN mkdir -p /app/data /app/dbdata

EXPOSE 8011

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8011"]

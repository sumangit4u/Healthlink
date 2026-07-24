# streamlit frontend image. Self-contained (no shared/ needed).
# Build context is the repo root (HealthLink/) for consistency with the others.
#   docker build -f services/streamlit/Dockerfile -t streamlit .
FROM python:3.11-slim

WORKDIR /app

COPY services/streamlit/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/streamlit/ ./

EXPOSE 8501

# headless + address 0.0.0.0 so the container is reachable; CORS/XSRF off since
# the app is served directly (no cross-site posting to it).
CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableCORS=false", \
     "--server.enableXsrfProtection=false"]

"""
api-gateway service - the public entry point.

Its job is deliberately short: validate -> forward to the orchestrator ->
return. It also proxies read-only doctor listing endpoints to the doctor-agent
so the frontend has a stable /api/v1 surface. No prompts, no model calls, no DB
live here. Session 7 security (validation, prompt-injection guard, PII-safe
logging, rate limiting) is applied on /assess.
"""
import logging
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from shared.config import get_settings
from shared.logging import setup_logging
from shared.schemas import HealthAssessmentRequest, HealthAssessmentResponse, HealthCheckResponse
from security import validate_user_input, detect_prompt_injection, mask_pii, RateLimiter

settings = get_settings()
logger = setup_logging(log_level=settings.log_level, service_name="healthlink.gateway")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8001")
DOCTOR_AGENT_URL = os.getenv("DOCTOR_AGENT_URL", "http://localhost:8011")
ASSESS_TIMEOUT = float(os.getenv("ASSESS_TIMEOUT_SECONDS", "180"))

rate_limiter = RateLimiter(
    max_requests=int(os.getenv("RATE_LIMIT_MAX", "20")),
    window_seconds=int(os.getenv("RATE_LIMIT_WINDOW", "60")),
)

app = FastAPI(
    title="HealthLink API Gateway",
    description="Public entry point - forwards work to the orchestrator.",
    version="1.0.0",
)

# CORS for the Streamlit frontend (and any browser client).
cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "name": "HealthLink API Gateway",
        "version": "1.0.0",
        "endpoints": {"docs": "/docs", "health": "/api/v1/health", "assess": "/api/v1/assess (POST)"},
    }


@app.get("/api/v1/health", response_model=HealthCheckResponse)
def health():
    orchestrator = "unreachable"
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(f"{ORCHESTRATOR_URL}/health")
            if r.status_code == 200:
                orchestrator = "healthy"
    except httpx.HTTPError:
        pass
    overall = "healthy" if orchestrator == "healthy" else "degraded"
    return HealthCheckResponse(status=overall, services={"orchestrator": orchestrator})


@app.post("/api/v1/assess", response_model=HealthAssessmentResponse)
def assess(request: HealthAssessmentRequest, http_request: Request) -> HealthAssessmentResponse:
    """Validate the request and forward it to the orchestrator."""
    client_id = http_request.client.host if http_request.client else "unknown"
    if not rate_limiter.allow(client_id):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again shortly.")

    is_valid, error = validate_user_input(request.user_input)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    if detect_prompt_injection(request.user_input):
        logger.warning(f"Prompt-injection attempt blocked from {client_id}")
        raise HTTPException(status_code=400, detail="Input rejected by safety filter.")

    logger.info(f"Assessment request from {client_id}: {mask_pii(request.user_input[:120])}")

    try:
        with httpx.Client(timeout=ASSESS_TIMEOUT) as client:
            resp = client.post(f"{ORCHESTRATOR_URL}/orchestrate", json=request.model_dump())
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Orchestrator unreachable: {exc}")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Orchestrator error: {resp.text}")
    return resp.json()


# ---- Doctor listing proxy (read-only) --------------------------------------

def _proxy_get(path: str):
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{DOCTOR_AGENT_URL}{path}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"doctor-agent unreachable: {exc}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@app.get("/api/v1/doctors")
def list_doctors():
    return _proxy_get("/doctors")


@app.get("/api/v1/doctors/{doctor_id}")
def get_doctor(doctor_id: int):
    return _proxy_get(f"/doctors/{doctor_id}")


@app.get("/api/v1/specialties")
def list_specialties():
    return _proxy_get("/specialties")

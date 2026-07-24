"""
orchestrator service - coordinates the 4 agent microservices over HTTP.

This is the monolith's core/orchestrator.py turned into a service: instead of
importing the agent functions and calling them in-process, it POSTs to each
agent service in sequence and threads the JSON output into the next call.
Internal microservice; only the api-gateway reaches it.
"""
import logging
import os
import uuid
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException

from shared.config import get_settings
from shared.logging import setup_logging
from shared.schemas import (
    HealthAssessmentRequest,
    HealthAssessmentResponse,
    SymptomExtraction,
    DoctorRecommendation,
    SchedulingRecommendation,
    HealthSummary,
    HealthCheckResponse,
)

settings = get_settings()
logger = setup_logging(log_level=settings.log_level, service_name="healthlink.orchestrator")

# Downstream agent URLs. In Azure Container Apps these are the internal app
# names (http://<app>); in docker-compose they are service names. Defaults are
# for running everything locally without containers.
SYMPTOM_AGENT_URL = os.getenv("SYMPTOM_AGENT_URL", "http://localhost:8010")
DOCTOR_AGENT_URL = os.getenv("DOCTOR_AGENT_URL", "http://localhost:8011")
SCHEDULING_AGENT_URL = os.getenv("SCHEDULING_AGENT_URL", "http://localhost:8012")
SUMMARY_AGENT_URL = os.getenv("SUMMARY_AGENT_URL", "http://localhost:8013")

AGENT_TIMEOUT = float(os.getenv("AGENT_TIMEOUT_SECONDS", "120"))

app = FastAPI(title="HealthLink orchestrator", version="1.0.0")


def _post(client: httpx.Client, url: str, path: str, payload: dict) -> dict:
    try:
        resp = client.post(f"{url}{path}", json=payload, timeout=AGENT_TIMEOUT)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Agent {url}{path} unreachable: {exc}")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Agent {url}{path} error: {resp.text}")
    return resp.json()


@app.get("/health", response_model=HealthCheckResponse)
def health():
    services = {}
    with httpx.Client(timeout=5) as client:
        for name, url in (
            ("symptom-agent", SYMPTOM_AGENT_URL),
            ("doctor-agent", DOCTOR_AGENT_URL),
            ("scheduling-agent", SCHEDULING_AGENT_URL),
            ("summary-agent", SUMMARY_AGENT_URL),
        ):
            try:
                r = client.get(f"{url}/health")
                services[name] = "healthy" if r.status_code == 200 else "unhealthy"
            except httpx.HTTPError:
                services[name] = "unreachable"
    overall = "healthy" if all(v == "healthy" for v in services.values()) else "degraded"
    return HealthCheckResponse(status=overall, services=services)


@app.post("/orchestrate", response_model=HealthAssessmentResponse)
def orchestrate(request: HealthAssessmentRequest) -> HealthAssessmentResponse:
    """Run the full 4-step assessment pipeline across the agent services."""
    request_id = str(uuid.uuid4())
    logger.info(f"[{request_id}] Starting orchestration")

    with httpx.Client() as client:
        # Step 1/4: symptom analysis
        logger.info(f"[{request_id}] Step 1/4: symptom-agent")
        symptom_analysis = SymptomExtraction(**_post(
            client, SYMPTOM_AGENT_URL, "/analyze",
            {"user_input": request.user_input, "use_rag": True},
        ))

        # Step 2/4: doctor recommendation
        logger.info(f"[{request_id}] Step 2/4: doctor-agent")
        doctor_recommendation = DoctorRecommendation(**_post(
            client, DOCTOR_AGENT_URL, "/recommend",
            {"symptom_analysis": symptom_analysis.model_dump(), "max_recommendations": 3},
        ))

        # Step 3/4: scheduling
        logger.info(f"[{request_id}] Step 3/4: scheduling-agent")
        scheduling_recommendation = SchedulingRecommendation(**_post(
            client, SCHEDULING_AGENT_URL, "/schedule",
            {
                "doctor_recommendation": doctor_recommendation.model_dump(),
                "urgency_level": symptom_analysis.urgency_level,
                "preferred_date": request.preferred_date,
            },
        ))

        # Step 4/4: summary
        logger.info(f"[{request_id}] Step 4/4: summary-agent")
        health_summary = HealthSummary(**_post(
            client, SUMMARY_AGENT_URL, "/summarize",
            {
                "symptom_analysis": symptom_analysis.model_dump(),
                "doctor_recommendation": doctor_recommendation.model_dump(),
                "scheduling_recommendation": scheduling_recommendation.model_dump(),
            },
        ))

    logger.info(f"[{request_id}] Orchestration complete")
    return HealthAssessmentResponse(
        request_id=request_id,
        timestamp=datetime.utcnow(),
        symptom_analysis=symptom_analysis,
        doctor_recommendations=doctor_recommendation,
        scheduling_options=scheduling_recommendation,
        health_summary=health_summary,
        metadata={
            "user_id": request.user_id,
            "preferred_location": request.preferred_location,
        },
    )

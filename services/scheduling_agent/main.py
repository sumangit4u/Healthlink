"""
scheduling-agent service - generates appointment slots and recommends one.
Internal microservice called by the orchestrator. Uses Gemini only.
"""
from fastapi import FastAPI

from shared.config import get_settings
from shared.logging import setup_logging
from shared.schemas import SchedulingAgentRequest, SchedulingRecommendation, HealthCheckResponse
from agent import scheduling_agent

settings = get_settings()
logger = setup_logging(log_level=settings.log_level, service_name="healthlink.scheduling")

app = FastAPI(title="HealthLink scheduling-agent", version="1.0.0")


@app.get("/health", response_model=HealthCheckResponse)
def health():
    return HealthCheckResponse(services={
        "llm": "healthy" if settings.gemini_api_key else "unavailable",
    })


@app.post("/schedule", response_model=SchedulingRecommendation)
def schedule(request: SchedulingAgentRequest) -> SchedulingRecommendation:
    """Generate scheduling options for the recommended doctors."""
    return scheduling_agent(
        doctor_recommendation=request.doctor_recommendation,
        urgency_level=request.urgency_level,
        settings=settings,
        preferred_date=request.preferred_date,
    )

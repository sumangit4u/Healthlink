"""
summary-agent service - synthesizes the final health summary.
Internal microservice called by the orchestrator. Uses Gemini only.
"""
from fastapi import FastAPI

from shared.config import get_settings
from shared.logging import setup_logging
from shared.schemas import SummaryAgentRequest, HealthSummary, HealthCheckResponse
from agent import summary_agent

settings = get_settings()
logger = setup_logging(log_level=settings.log_level, service_name="healthlink.summary")

app = FastAPI(title="HealthLink summary-agent", version="1.0.0")


@app.get("/health", response_model=HealthCheckResponse)
def health():
    return HealthCheckResponse(services={
        "llm": "healthy" if settings.gemini_api_key else "unavailable",
    })


@app.post("/summarize", response_model=HealthSummary)
def summarize(request: SummaryAgentRequest) -> HealthSummary:
    """Produce the final comprehensive health summary."""
    return summary_agent(
        symptom_analysis=request.symptom_analysis,
        doctor_recommendation=request.doctor_recommendation,
        scheduling_recommendation=request.scheduling_recommendation,
        settings=settings,
    )

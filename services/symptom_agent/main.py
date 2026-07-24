"""
symptom-agent service - extracts symptoms + urgency from free text.
Internal microservice called by the orchestrator. Uses Gemini + Pinecone (RAG).
"""
import logging
import os

from fastapi import FastAPI

from shared.config import get_settings
from shared.logging import setup_logging
from shared.schemas import SymptomAgentRequest, SymptomExtraction, HealthCheckResponse
from agent import symptom_agent

settings = get_settings()
logger = setup_logging(log_level=settings.log_level, service_name="healthlink.symptom")

app = FastAPI(title="HealthLink symptom-agent", version="1.0.0")


@app.on_event("startup")
def load_kb_if_requested():
    """Optionally (re)index the knowledge base into Pinecone on startup.

    The Pinecone index persists across restarts, so this only needs to run once.
    Set LOAD_KB_ON_STARTUP=true (and provide data/symptoms_kb.json) to seed it.
    """
    if os.getenv("LOAD_KB_ON_STARTUP", "false").lower() != "true":
        return
    kb_file = os.getenv("KB_FILE", "./data/symptoms_kb.json")
    if not os.path.exists(kb_file):
        logger.warning(f"LOAD_KB_ON_STARTUP set but KB file not found: {kb_file}")
        return
    try:
        from rag import load_knowledge_base
        load_knowledge_base(kb_file, settings)
        logger.info("Knowledge base loaded into Pinecone")
    except Exception as e:
        logger.error(f"Knowledge base load failed: {e}", exc_info=True)


@app.get("/health", response_model=HealthCheckResponse)
def health():
    return HealthCheckResponse(services={
        "llm": "healthy" if settings.gemini_api_key else "unavailable",
        "pinecone": "configured" if settings.pinecone_api_key else "unavailable",
    })


@app.post("/analyze", response_model=SymptomExtraction)
def analyze(request: SymptomAgentRequest) -> SymptomExtraction:
    """Extract symptoms and urgency from the user's description."""
    return symptom_agent(
        user_input=request.user_input,
        settings=settings,
        use_rag=request.use_rag,
    )

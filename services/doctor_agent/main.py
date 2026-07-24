"""
doctor-agent service - recommends doctors for a symptom analysis and owns the
doctor store. Internal microservice called by the orchestrator (recommend) and
proxied by the api-gateway (doctor listing). Uses Gemini + SQLAlchemy.
"""
import csv
import logging
import os
from typing import List

from fastapi import FastAPI, HTTPException

from shared.config import get_settings
from shared.logging import setup_logging
from shared.schemas import (
    DoctorAgentRequest,
    DoctorRecommendation,
    DoctorDB,
    HealthCheckResponse,
)
from database import (
    get_db_manager,
    get_all_doctors,
    get_doctor_by_id,
    get_specialties,
    seed_doctors,
)
from agent import doctor_agent

settings = get_settings()
logger = setup_logging(log_level=settings.log_level, service_name="healthlink.doctor")

app = FastAPI(title="HealthLink doctor-agent", version="1.0.0")

_INT_FIELDS = {"experience_years"}
_FLOAT_FIELDS = {"rating"}


def _load_doctors_csv(path: str) -> List[dict]:
    rows: List[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for field in _INT_FIELDS:
                if row.get(field):
                    row[field] = int(row[field])
            for field in _FLOAT_FIELDS:
                if row.get(field):
                    row[field] = float(row[field])
            rows.append(row)
    return rows


@app.on_event("startup")
def seed_on_startup():
    """Create tables and seed doctors from the bundled CSV (idempotent)."""
    db_manager = get_db_manager(settings)
    csv_file = os.getenv("DOCTORS_CSV", "./data/doctors.csv")
    if not os.path.exists(csv_file):
        logger.warning(f"Doctors CSV not found: {csv_file} (DB will be empty)")
        return
    try:
        doctors_data = _load_doctors_csv(csv_file)
        with db_manager.session_scope() as session:
            seed_doctors(session, doctors_data)
    except Exception as e:
        logger.error(f"Doctor seeding failed: {e}", exc_info=True)


@app.get("/health", response_model=HealthCheckResponse)
def health():
    db_status = "healthy"
    try:
        with get_db_manager(settings).session_scope() as session:
            get_all_doctors(session)
    except Exception:
        db_status = "unavailable"
    return HealthCheckResponse(services={
        "llm": "healthy" if settings.gemini_api_key else "unavailable",
        "database": db_status,
    })


@app.post("/recommend", response_model=DoctorRecommendation)
def recommend(request: DoctorAgentRequest) -> DoctorRecommendation:
    """Recommend doctors for a symptom analysis."""
    db_manager = get_db_manager(settings)
    with db_manager.session_scope() as session:
        return doctor_agent(
            symptom_analysis=request.symptom_analysis,
            db_session=session,
            settings=settings,
            max_recommendations=request.max_recommendations,
        )


@app.get("/doctors", response_model=List[DoctorDB])
def list_doctors() -> List[DoctorDB]:
    with get_db_manager(settings).session_scope() as session:
        return [DoctorDB.model_validate(d, from_attributes=True) for d in get_all_doctors(session)]


@app.get("/doctors/{doctor_id}", response_model=DoctorDB)
def get_doctor(doctor_id: int) -> DoctorDB:
    with get_db_manager(settings).session_scope() as session:
        doctor = get_doctor_by_id(session, doctor_id)
        if doctor is None:
            raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found")
        return DoctorDB.model_validate(doctor, from_attributes=True)


@app.get("/specialties", response_model=List[str])
def list_specialties() -> List[str]:
    with get_db_manager(settings).session_scope() as session:
        return get_specialties(session)

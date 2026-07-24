"""
Summary agent logic.
Creates a comprehensive health summary from all prior agent outputs.
"""
import logging
from typing import Optional

from shared.llm import llm_generate, LLMClient
from shared.schemas import (
    SymptomExtraction,
    DoctorRecommendation,
    SchedulingRecommendation,
    HealthSummary,
)
from shared.config import Settings, get_settings


logger = logging.getLogger("healthlink.summary.agent")


def summary_agent(
    symptom_analysis: SymptomExtraction,
    doctor_recommendation: DoctorRecommendation,
    scheduling_recommendation: SchedulingRecommendation,
    llm_client: Optional[LLMClient] = None,
    settings: Optional[Settings] = None
) -> HealthSummary:
    """Generate a comprehensive health summary from all agent outputs."""
    logger.info("Summary agent generating comprehensive health summary")

    if settings is None:
        settings = get_settings()

    symptoms_text = ", ".join([
        f"{s.name} ({s.severity})" for s in symptom_analysis.symptoms
    ])

    doctors_text = ", ".join([
        f"Dr. {d.name} ({d.specialty})" for d in doctor_recommendation.recommended_doctors
    ])

    recommended_slot = scheduling_recommendation.recommended_slot
    slot_text = (
        f"{recommended_slot.doctor_name} on {recommended_slot.date} at {recommended_slot.time}"
        if recommended_slot
        else "No specific slot recommended"
    )

    summary_prompt = f"""Generate a comprehensive health assessment summary based on the following information:

SYMPTOM ANALYSIS:
- Primary Complaint: {symptom_analysis.primary_complaint}
- Symptoms Identified: {symptoms_text}
- Urgency Level: {symptom_analysis.urgency_level}
- Additional Context: {symptom_analysis.additional_context or 'None'}

DOCTOR RECOMMENDATIONS:
- Recommended Doctors: {doctors_text}
- Specialty Rationale: {doctor_recommendation.specialty_rationale}
- Match Confidence: {doctor_recommendation.match_score}

SCHEDULING:
- Recommended Appointment: {slot_text}
- Scheduling Notes: {scheduling_recommendation.scheduling_notes or 'None'}

Generate a summary that includes:
1. A clear, empathetic overview of the health situation (2-3 sentences)
2. Key medical findings from the symptom analysis (list format)
3. Recommended next steps including doctor consultation and appointment (list format)
4. Overall urgency assessment with explanation

IMPORTANT:
- Be professional and empathetic
- Avoid making definitive medical diagnoses
- Emphasize that this is guidance, not medical advice
- Use clear, patient-friendly language
- Include the mandatory disclaimer
"""

    try:
        result = llm_generate(
            prompt=summary_prompt,
            schema=HealthSummary,
            temperature=0.3,
            client=llm_client
        )

        if not result.disclaimer:
            result.disclaimer = (
                "This is not a medical diagnosis. Please consult with healthcare "
                "professionals for medical advice."
            )

        logger.info("Summary generation complete")
        return result

    except Exception as e:
        logger.error(f"Summary agent failed: {e}", exc_info=True)

        return HealthSummary(
            summary=(
                f"Based on your reported symptoms ({symptom_analysis.primary_complaint}), "
                f"we recommend consulting with a healthcare professional. "
                f"The urgency level has been assessed as {symptom_analysis.urgency_level}."
            ),
            key_findings=[
                f"Primary complaint: {symptom_analysis.primary_complaint}",
                f"Urgency level: {symptom_analysis.urgency_level}",
                f"Recommended specialty: {doctor_recommendation.recommended_doctors[0].specialty if doctor_recommendation.recommended_doctors else 'General Practice'}"
            ],
            recommended_actions=[
                "Schedule an appointment with a recommended healthcare provider",
                "Monitor your symptoms and seek immediate care if they worsen",
                "Bring any relevant medical history to your appointment"
            ],
            urgency_assessment=symptom_analysis.urgency_level,
            disclaimer=(
                "This is not a medical diagnosis. Please consult with healthcare "
                "professionals for medical advice."
            )
        )

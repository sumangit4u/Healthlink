"""
Symptom extraction agent logic.
Analyzes user input to extract symptoms, severity, and urgency.
"""
import logging
from typing import Optional

from shared.llm import llm_generate, LLMClient
from shared.schemas import SymptomExtraction
from shared.config import Settings, get_settings
from rag import retrieve_relevant_docs, format_retrieval_context


logger = logging.getLogger("healthlink.symptom.agent")


def symptom_agent(
    user_input: str,
    llm_client: Optional[LLMClient] = None,
    settings: Optional[Settings] = None,
    use_rag: bool = True
) -> SymptomExtraction:
    """Extract symptoms and assess urgency from user input."""
    logger.info("Symptom agent processing user input")

    if settings is None:
        settings = get_settings()

    context = ""
    if use_rag:
        try:
            retrieval_result = retrieve_relevant_docs(user_input, k=settings.rag_top_k, settings=settings)
            context = format_retrieval_context(retrieval_result, max_docs=3)
            logger.debug(f"Retrieved {len(retrieval_result.documents)} relevant documents")
        except Exception as e:
            logger.warning(f"RAG retrieval failed: {e}. Continuing without context.")

    prompt = f"""Analyze the following patient complaint and extract structured symptom information.

Patient Input: "{user_input}"

Your task:
1. Identify all mentioned symptoms with their severity (mild, moderate, severe)
2. Note symptom duration if mentioned
3. Determine the primary health complaint
4. Assess urgency level based on symptoms:
   - emergency: Life-threatening symptoms (chest pain, difficulty breathing, severe bleeding, etc.)
   - high: Severe symptoms requiring prompt medical attention
   - medium: Moderate symptoms that should be evaluated soon
   - low: Mild symptoms for routine consultation

Be conservative with urgency assessment - if uncertain, err on the side of higher urgency.
"""

    try:
        result = llm_generate(
            prompt=prompt,
            schema=SymptomExtraction,
            temperature=0.2,
            context=context,
            client=llm_client
        )

        logger.info(
            f"Symptom extraction complete: "
            f"{len(result.symptoms)} symptoms, urgency={result.urgency_level}"
        )

        return result

    except Exception as e:
        logger.error(f"Symptom agent failed: {e}", exc_info=True)
        return SymptomExtraction(
            symptoms=[],
            primary_complaint=user_input[:100],
            urgency_level="medium",
            additional_context="Error occurred during symptom analysis. Please consult a healthcare provider."
        )

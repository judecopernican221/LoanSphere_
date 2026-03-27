"""
RAG Service
────────────
The core AI intelligence of the system.

Flow:
  1. Retrieve top-5 similar historical applications from Qdrant
  2. Build a grounded prompt with that context
  3. Call Groq LLM (llama3-8b) — temperature=0.1 for determinism
  4. Parse the structured JSON response
  5. Fall back to rule-based assessment if LLM fails
"""
import json
import re
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import RAGAssessment
from app.services.embedding_service import search_similar_applications

logger = get_logger(__name__)


def _build_rag_prompt(application, similar_cases: list[dict]) -> str:
    """
    Build the RAG prompt that grounds the LLM in real historical data.
    The more specific the context, the less the LLM hallucinates.
    """
    # Format similar cases as context
    if similar_cases:
        context_lines = []
        for i, case in enumerate(similar_cases, 1):
            context_lines.append(
                f"Case {i}: Credit={case.get('credit_score_band','?')}, "
                f"Employment={case.get('employment_type','?')}, "
                f"Risk={case.get('risk_level','?')}, "
                f"Outcome={case.get('outcome','?')} "
                f"(similarity={case.get('score', 0):.2f})"
            )
        context = "\n".join(context_lines)
    else:
        context = "No similar historical cases found. Assess based on financial indicators only."

    dti_pct = round((application.debt_to_income_ratio or 0) * 100, 1)
    lti = round(application.loan_to_income_ratio or 0, 2)

    prompt = f"""You are a senior loan risk analyst at a financial institution. Analyze this loan application and provide a structured risk assessment.

HISTORICAL CONTEXT (similar past applications):
{context}

CURRENT APPLICATION:
- Applicant: {application.applicant_name}
- Loan Amount: ₹{application.loan_amount:,.0f}
- Purpose: {application.loan_purpose or 'Not specified'}
- Employment: {application.employment_type}
- Annual Income: ₹{application.annual_income:,.0f}
- Credit Score: {application.credit_score}
- Existing Debt: ₹{application.existing_debt:,.0f}
- Debt-to-Income Ratio: {dti_pct}%
- Loan-to-Income Ratio: {lti}x

Based on the historical cases and current application data, provide your assessment.

Respond ONLY with valid JSON in this exact format:
{{
    "risk_level": "low|medium|high",
    "key_concerns": "comma-separated list of specific risk factors, or 'none' if low risk",
    "recommendation": "approve|reject|manual_review",
    "confidence_score": 0.85,
    "reasoning": "2-3 sentence explanation referencing the historical cases"
}}"""

    return prompt


def _rule_based_assessment(application) -> RAGAssessment:
    """
    Deterministic fallback when LLM is unavailable.
    Uses the same thresholds as the decision engine.
    """
    credit = application.credit_score or 0
    dti = application.debt_to_income_ratio or 0
    lti = application.loan_to_income_ratio or 0

    concerns = []

    if credit >= 750 and dti <= 0.35 and lti <= 4:
        risk_level = "low"
        recommendation = "approve"
        confidence = 0.82
    elif credit < 600 or dti > 0.65:
        risk_level = "high"
        recommendation = "reject"
        confidence = 0.80
        if credit < 600:
            concerns.append(f"credit score {credit} below minimum threshold")
        if dti > 0.65:
            concerns.append(f"DTI {dti*100:.0f}% exceeds 65% limit")
    else:
        risk_level = "medium"
        recommendation = "manual_review"
        confidence = 0.70
        if credit < 700:
            concerns.append(f"credit score {credit} below preferred threshold")
        if dti > 0.40:
            concerns.append(f"elevated DTI at {dti*100:.0f}%")
        if lti > 5:
            concerns.append(f"high loan-to-income ratio {lti:.1f}x")

    return RAGAssessment(
        risk_level=risk_level,
        key_concerns=", ".join(concerns) if concerns else "none",
        recommendation=recommendation,
        confidence_score=confidence,
        reasoning="Rule-based assessment (LLM unavailable). Based on credit score, DTI, and LTI thresholds.",
    )


def _parse_llm_response(raw_text: str) -> Optional[RAGAssessment]:
    """
    Parse the LLM's JSON response safely.
    LLMs sometimes add markdown fences or extra text — we handle that.
    """
    try:
        # Strip markdown code fences if present
        text = raw_text.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        data = json.loads(text)

        # Validate required fields
        risk_level = data.get("risk_level", "").lower()
        if risk_level not in {"low", "medium", "high"}:
            raise ValueError(f"Invalid risk_level: {risk_level}")

        recommendation = data.get("recommendation", "").lower()
        if recommendation not in {"approve", "reject", "manual_review"}:
            recommendation = "manual_review"

        confidence = float(data.get("confidence_score", 0.7))
        confidence = max(0.0, min(1.0, confidence))  # clamp 0-1

        return RAGAssessment(
            risk_level=risk_level,
            key_concerns=str(data.get("key_concerns", "none")),
            recommendation=recommendation,
            confidence_score=confidence,
            reasoning=str(data.get("reasoning", "")),
        )

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("llm_response_parse_failed", error=str(e), raw=raw_text[:200])
        return None


def run_rag_assessment(application) -> RAGAssessment:
    """
    Main entry point: run the full RAG pipeline for a loan application.

    Steps:
      1. Search for similar historical cases in Qdrant
      2. Build RAG prompt with that context
      3. Call Groq LLM
      4. Parse the response
      5. Fall back to rule-based if any step fails
    """
    # Step 1: Retrieve similar cases
    similar_cases = search_similar_applications(application, limit=5)
    logger.info("similar_cases_retrieved", count=len(similar_cases), application_id=str(application.id))

    # Step 2: Check for Groq API key
    if not settings.GROQ_API_KEY or settings.GROQ_API_KEY == "gsk_your_key_here":
        logger.warning("groq_api_key_missing_using_fallback")
        return _rule_based_assessment(application)

    # Step 3: Call Groq LLM
    try:
        from groq import Groq

        client = Groq(api_key=settings.GROQ_API_KEY)
        prompt = _build_rag_prompt(application, similar_cases)

        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=settings.GROQ_TEMPERATURE,
            max_tokens=500,
        )

        raw_text = response.choices[0].message.content
        logger.info("groq_response_received", application_id=str(application.id), tokens=len(raw_text))

        # Step 4: Parse response
        assessment = _parse_llm_response(raw_text)
        if assessment:
            return assessment

        # If parsing fails, fall through to fallback
        logger.warning("llm_parse_failed_using_fallback", application_id=str(application.id))

    except Exception as e:
        logger.error("groq_api_failed", application_id=str(application.id), error=str(e))

    # Step 5: Rule-based fallback
    return _rule_based_assessment(application)

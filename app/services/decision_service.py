"""
Decision Engine
───────────────
Applies deterministic business rules on top of the probabilistic LLM output.

Why deterministic rules on top of AI?
  LLMs are probabilistic — same input can produce slightly different output.
  Enterprise systems need reproducible, auditable decisions.
  The hybrid approach: AI gives intelligence, rules give guardrails.

Decision hierarchy:
  AUTO_APPROVE  — clear-cut safe loans, instantly approved
  AUTO_REJECT   — clear-cut risky loans, instantly rejected
  MANUAL_REVIEW — everything else goes to a human engineer
"""
from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import RAGAssessment, DecisionResult

logger = get_logger(__name__)


def make_decision(application, assessment: RAGAssessment) -> DecisionResult:
    """
    Apply business rules to produce a final decision.

    Inputs:
      application — the LoanApplication ORM object
      assessment  — the RAGAssessment from the LLM or fallback

    Returns:
      DecisionResult with decision, reason, risk_level, confidence_score
    """
    credit = application.credit_score or 0
    dti    = application.debt_to_income_ratio or 0.0
    lti    = application.loan_to_income_ratio or 0.0
    risk   = assessment.risk_level
    conf   = assessment.confidence_score

    logger.info(
        "decision_engine_running",
        application_id=str(application.id),
        credit=credit, dti=dti, lti=lti,
        risk=risk, confidence=conf,
    )

    # ── AUTO APPROVE ────────────────────────────────────────────────────────
    # All conditions must be met:
    if (
        risk == "low"
        and credit >= settings.AUTO_APPROVE_MIN_CREDIT     # default 700
        and conf  >= settings.CONFIDENCE_THRESHOLD          # default 0.80
        and dti   <= settings.AUTO_APPROVE_MAX_DTI          # default 0.40
        and lti   <= settings.AUTO_APPROVE_MAX_LTI          # default 5.0
    ):
        return DecisionResult(
            decision="AUTO_APPROVE",
            reason=(
                f"Auto-approved: low risk profile. "
                f"Credit score {credit} ≥ {settings.AUTO_APPROVE_MIN_CREDIT}, "
                f"DTI {dti*100:.1f}% ≤ {settings.AUTO_APPROVE_MAX_DTI*100:.0f}%, "
                f"LTI {lti:.1f}x ≤ {settings.AUTO_APPROVE_MAX_LTI}x, "
                f"AI confidence {conf:.0%}."
            ),
            risk_level=risk,
            confidence_score=conf,
        )

    # ── AUTO REJECT ─────────────────────────────────────────────────────────
    # Any of these hard disqualifiers triggers rejection:
    hard_reject_reasons = []

    if credit < settings.AUTO_REJECT_MAX_CREDIT:            # default 600
        hard_reject_reasons.append(f"credit score {credit} below minimum {settings.AUTO_REJECT_MAX_CREDIT}")

    if dti > settings.AUTO_REJECT_MIN_DTI:                  # default 0.65
        hard_reject_reasons.append(f"DTI {dti*100:.1f}% exceeds maximum {settings.AUTO_REJECT_MIN_DTI*100:.0f}%")

    if risk == "high" and hard_reject_reasons and conf >= settings.CONFIDENCE_THRESHOLD:
        return DecisionResult(
            decision="AUTO_REJECT",
            reason=f"Auto-rejected: {'; '.join(hard_reject_reasons)}. AI confidence {conf:.0%}.",
            risk_level=risk,
            confidence_score=conf,
        )

    # ── MANUAL REVIEW ───────────────────────────────────────────────────────
    # Everything else — borderline cases, low confidence, medium risk
    review_reasons = []

    if risk == "medium":
        review_reasons.append("medium risk profile requires human judgement")
    if conf < settings.CONFIDENCE_THRESHOLD:
        review_reasons.append(f"AI confidence {conf:.0%} below {settings.CONFIDENCE_THRESHOLD:.0%} threshold")
    if hard_reject_reasons:
        review_reasons.append(f"risk factors: {'; '.join(hard_reject_reasons)}")
    if assessment.key_concerns and assessment.key_concerns != "none":
        review_reasons.append(f"concerns: {assessment.key_concerns}")
    if not review_reasons:
        review_reasons.append("does not meet auto-approve criteria")

    return DecisionResult(
        decision="MANUAL_REVIEW",
        reason=f"Flagged for manual review: {'; '.join(review_reasons)}.",
        risk_level=risk,
        confidence_score=conf,
    )

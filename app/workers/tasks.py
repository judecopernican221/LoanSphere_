"""
Celery Tasks
─────────────
The main background task that runs the full AI pipeline for each loan application.

This runs in a separate Celery worker process, completely independent of the API.
The API submits the task and returns 202 immediately — the client polls for results.

Pipeline:
  Load application → Extract PDF → Embed → Search similar → RAG LLM → Decide → Store
"""
import asyncio
from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.core.logging import get_logger

logger = get_logger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="process_application",
)
def process_application_task(self, application_id: str):
    """
    Full AI pipeline for a single loan application.
    Bound task (bind=True) gives access to self for retry logic.
    """
    logger.info("task_started", application_id=application_id, attempt=self.request.retries + 1)

    try:
        _run_async(_process_application_async(application_id))
        logger.info("task_completed", application_id=application_id)

    except Exception as exc:
        logger.error("task_failed", application_id=application_id, error=str(exc), attempt=self.request.retries + 1)

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))

        # All retries exhausted — mark as failed
        _run_async(_mark_failed(application_id, str(exc)))


async def _process_application_async(application_id: str):
    """
    The actual async pipeline. Runs inside a new event loop created by Celery.
    """
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.database import LoanApplication, AuditLog
    from app.services.pdf_service import extract_text_from_pdf
    from app.services.embedding_service import upsert_application_vector, search_similar_applications
    from app.services.rag_service import run_rag_assessment
    from app.services.decision_service import make_decision

    async with AsyncSessionLocal() as db:
        # ── Step 1: Load application ───────────────────────────────────────
        result = await db.execute(
            select(LoanApplication).where(LoanApplication.id == application_id)
        )
        application = result.scalar_one_or_none()

        if not application:
            raise ValueError(f"Application {application_id} not found")

        # Mark as processing
        application.status = "processing"
        db.add(AuditLog(
            application_id=application.id,
            action="PROCESSING_STARTED",
            details="AI pipeline started",
            actor="system",
        ))
        await db.commit()

        # ── Step 2: Extract PDF text (if uploaded) ─────────────────────────
        if application.pdf_path:
            extracted = extract_text_from_pdf(application.pdf_path)
            if extracted:
                application.extracted_text = extracted
                logger.info("pdf_text_extracted", application_id=application_id, chars=len(extracted))

        # ── Step 3: Run RAG assessment ─────────────────────────────────────
        assessment = run_rag_assessment(application)
        logger.info(
            "rag_assessment_complete",
            application_id=application_id,
            risk=assessment.risk_level,
            confidence=assessment.confidence_score,
        )

        # ── Step 4: Apply decision engine ──────────────────────────────────
        decision_result = make_decision(application, assessment)
        logger.info(
            "decision_made",
            application_id=application_id,
            decision=decision_result.decision,
        )

        # ── Step 5: Update application record ──────────────────────────────
        status_map = {
            "AUTO_APPROVE":  "auto_approved",
            "AUTO_REJECT":   "auto_rejected",
            "MANUAL_REVIEW": "manual_review",
        }
        application.status          = status_map[decision_result.decision]
        application.risk_level      = assessment.risk_level
        application.risk_assessment = assessment.reasoning
        application.key_concerns    = assessment.key_concerns
        application.recommendation  = assessment.recommendation
        application.confidence_score = assessment.confidence_score
        application.decision        = decision_result.decision
        application.decision_reason = decision_result.reason
        application.processed_at    = datetime.now(timezone.utc)

        db.add(AuditLog(
            application_id=application.id,
            action="DECISION_MADE",
            details=(
                f"Decision: {decision_result.decision} | "
                f"Risk: {assessment.risk_level} | "
                f"Confidence: {assessment.confidence_score:.0%} | "
                f"Reason: {decision_result.reason[:200]}"
            ),
            actor="system",
        ))
        await db.commit()

        # ── Step 6: Store embedding in Qdrant ──────────────────────────────
        success = upsert_application_vector(application, outcome=decision_result.decision)
        if success:
            application.is_embedded = True
            db.add(AuditLog(
                application_id=application.id,
                action="EMBEDDING_STORED",
                details=f"Vector stored in Qdrant collection: {application.id}",
                actor="system",
            ))
            await db.commit()

        logger.info("pipeline_complete", application_id=application_id, decision=decision_result.decision)


async def _mark_failed(application_id: str, error: str):
    """Mark application as failed after all retries exhausted."""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.database import LoanApplication, AuditLog

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(LoanApplication).where(LoanApplication.id == application_id)
        )
        application = result.scalar_one_or_none()
        if application:
            application.status = "manual_review"
            application.decision_reason = f"Processing failed after retries: {error[:200]}"
            db.add(AuditLog(
                application_id=application.id,
                action="PROCESSING_FAILED",
                details=f"All retries exhausted: {error[:200]}",
                actor="system",
            ))
            await db.commit()

import uuid
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import UserRole
from app.models.database import User, LoanApplication, AuditLog
from app.models.schemas import (
    LoanApplicationResponse, ApplicationListResponse,
    ManualReviewRequest, AuditTrailResponse, AuditLogResponse,
)
from app.api.deps import get_current_user, require_role
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _calc_ratios(loan_amount: float, annual_income: float, existing_debt: float):
    """Calculate Debt-to-Income and Loan-to-Income ratios."""
    dti = round(existing_debt / annual_income, 4) if annual_income > 0 else None
    lti = round(loan_amount / annual_income, 4) if annual_income > 0 else None
    return dti, lti


async def _add_audit(
    db: AsyncSession,
    application_id: uuid.UUID,
    action: str,
    details: str,
    actor: str,
    actor_user_id: Optional[uuid.UUID] = None,
):
    """Helper: insert one immutable audit log row."""
    log = AuditLog(
        application_id=application_id,
        action=action,
        details=details,
        actor=actor,
        actor_user_id=actor_user_id,
    )
    db.add(log)


# ─── Submit Application ────────────────────────────────────────────────────────

@router.post("/submit", response_model=LoanApplicationResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_application(
    background_tasks: BackgroundTasks,
    # Form fields (supports multipart so we can also accept a PDF)
    applicant_name: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(default=None),
    loan_amount: float = Form(...),
    loan_purpose: Optional[str] = Form(default=None),
    employment_type: str = Form(...),
    annual_income: float = Form(...),
    credit_score: int = Form(...),
    existing_debt: float = Form(default=0.0),
    pdf_file: Optional[UploadFile] = File(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ENGINEER)),
):
    """
    Submit a new loan application.
    Returns 202 Accepted immediately.
    AI processing happens asynchronously via Celery.
    """
    # Validate employment type
    if employment_type not in {"salaried", "self_employed", "business"}:
        raise HTTPException(status_code=400, detail="employment_type must be salaried | self_employed | business")

    if credit_score < 300 or credit_score > 900:
        raise HTTPException(status_code=400, detail="credit_score must be between 300 and 900")

    # Save PDF if uploaded
    pdf_path = None
    if pdf_file and pdf_file.filename:
        safe_name = f"{uuid.uuid4()}_{pdf_file.filename}"
        pdf_path = os.path.join(UPLOAD_DIR, safe_name)
        content = await pdf_file.read()
        with open(pdf_path, "wb") as f:
            f.write(content)

    # Calculate financial ratios
    dti, lti = _calc_ratios(loan_amount, annual_income, existing_debt)

    # Create application record
    application = LoanApplication(
        applicant_name=applicant_name,
        email=email,
        phone=phone,
        loan_amount=loan_amount,
        loan_purpose=loan_purpose,
        employment_type=employment_type,
        annual_income=annual_income,
        credit_score=credit_score,
        existing_debt=existing_debt,
        debt_to_income_ratio=dti,
        loan_to_income_ratio=lti,
        pdf_path=pdf_path,
        status="pending",
        submitted_by=current_user.id,
    )
    db.add(application)
    await db.flush()

    # Audit log
    await _add_audit(
        db, application.id,
        action="APPLICATION_SUBMITTED",
        details=f"Loan: ₹{loan_amount:,.0f} | Purpose: {loan_purpose} | DTI: {dti}",
        actor=current_user.username,
        actor_user_id=current_user.id,
    )

    # Trigger async AI processing
    background_tasks.add_task(_trigger_processing, str(application.id))

    logger.info("application_submitted", application_id=str(application.id), applicant=applicant_name)
    return application


def _trigger_processing(application_id: str):
    """Send task to Celery worker for AI processing."""
    try:
        from app.workers.tasks import process_application_task
        process_application_task.delay(application_id)
        logger.info("celery_task_enqueued", application_id=application_id)
    except Exception as e:
        logger.error("celery_enqueue_failed", application_id=application_id, error=str(e))


# ─── Get Single Application ────────────────────────────────────────────────────

@router.get("/{application_id}", response_model=LoanApplicationResponse)
async def get_application(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(LoanApplication).where(LoanApplication.id == application_id))
    application = result.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


# ─── List All Applications ─────────────────────────────────────────────────────

@router.get("/", response_model=ApplicationListResponse)
async def list_applications(
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all applications with optional status filter and pagination."""
    query = select(LoanApplication)
    if status_filter:
        query = query.where(LoanApplication.status == status_filter)

    query = query.order_by(LoanApplication.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    applications = result.scalars().all()

    # Count total
    count_query = select(func.count(LoanApplication.id))
    if status_filter:
        count_query = count_query.where(LoanApplication.status == status_filter)
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    return ApplicationListResponse(total=total, applications=list(applications))


# ─── Manual Review ─────────────────────────────────────────────────────────────

@router.patch("/{application_id}/review", response_model=LoanApplicationResponse)
async def manual_review(
    application_id: uuid.UUID,
    payload: ManualReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ENGINEER)),
):
    """
    Engineer manually approves or rejects a MANUAL_REVIEW application.
    Only applications in 'manual_review' status can be acted on.
    """
    result = await db.execute(select(LoanApplication).where(LoanApplication.id == application_id))
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    if application.status != "manual_review":
        raise HTTPException(
            status_code=400,
            detail=f"Can only review applications in 'manual_review' status. Current: {application.status}",
        )

    if payload.decision == "approve":
        application.status = "manually_approved"
        application.decision = "MANUAL_APPROVE"
        action = "MANUAL_APPROVED"
    else:
        application.status = "manually_rejected"
        application.decision = "MANUAL_REJECT"
        action = "MANUAL_REJECTED"

    application.decision_reason = payload.reason

    await _add_audit(
        db, application.id,
        action=action,
        details=f"Manual decision by {current_user.username}: {payload.reason}",
        actor=current_user.username,
        actor_user_id=current_user.id,
    )

    logger.info("manual_review_done", application_id=str(application_id), decision=payload.decision, reviewer=current_user.username)
    return application


# ─── Audit Trail ───────────────────────────────────────────────────────────────

@router.get("/{application_id}/audit", response_model=AuditTrailResponse)
async def get_audit_trail(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return full immutable audit trail for an application."""
    # Verify application exists
    result = await db.execute(select(LoanApplication).where(LoanApplication.id == application_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Application not found")

    logs_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.application_id == application_id)
        .order_by(AuditLog.created_at.asc())
    )
    logs = logs_result.scalars().all()

    return AuditTrailResponse(
        application_id=application_id,
        logs=[AuditLogResponse.model_validate(log) for log in logs],
    )

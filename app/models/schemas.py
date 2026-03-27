import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ─── Auth Schemas ──────────────────────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., min_length=5, max_length=200)
    password: str = Field(..., min_length=6, max_length=100)
    role: str = Field(default="viewer")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"admin", "engineer", "viewer"}
        if v not in allowed:
            raise ValueError(f"Role must be one of {allowed}")
        return v


class UserLoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Application Schemas ───────────────────────────────────────────────────────

class LoanApplicationRequest(BaseModel):
    applicant_name: str = Field(..., min_length=2, max_length=200)
    email: str = Field(..., min_length=5, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=20)
    loan_amount: float = Field(..., gt=0, description="Loan amount in rupees")
    loan_purpose: Optional[str] = Field(default=None, max_length=500)
    employment_type: str = Field(..., description="salaried | self_employed | business")
    annual_income: float = Field(..., gt=0)
    credit_score: int = Field(..., ge=300, le=900)
    existing_debt: float = Field(default=0.0, ge=0)

    @field_validator("employment_type")
    @classmethod
    def validate_employment(cls, v: str) -> str:
        allowed = {"salaried", "self_employed", "business"}
        if v not in allowed:
            raise ValueError(f"employment_type must be one of {allowed}")
        return v


class LoanApplicationResponse(BaseModel):
    id: uuid.UUID
    applicant_name: str
    email: str
    phone: Optional[str]
    loan_amount: float
    loan_purpose: Optional[str]
    employment_type: Optional[str]
    annual_income: Optional[float]
    credit_score: Optional[int]
    existing_debt: Optional[float]
    debt_to_income_ratio: Optional[float]
    loan_to_income_ratio: Optional[float]
    status: str
    risk_level: Optional[str]
    risk_assessment: Optional[str]
    key_concerns: Optional[str]
    recommendation: Optional[str]
    confidence_score: Optional[float]
    decision: Optional[str]
    decision_reason: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ApplicationListResponse(BaseModel):
    total: int
    applications: list[LoanApplicationResponse]


class ManualReviewRequest(BaseModel):
    decision: str = Field(..., description="approve | reject")
    reason: str = Field(..., min_length=10, max_length=1000)

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        if v not in {"approve", "reject"}:
            raise ValueError("decision must be 'approve' or 'reject'")
        return v


# ─── Audit Log Schemas ─────────────────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    id: uuid.UUID
    action: str
    details: Optional[str]
    actor: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditTrailResponse(BaseModel):
    application_id: uuid.UUID
    logs: list[AuditLogResponse]


# ─── Health Check ──────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str
    services: Optional[dict] = None


# ─── Internal AI Pipeline Schemas (not exposed via API) ───────────────────────

class RAGAssessment(BaseModel):
    """Structured output from the Groq LLM."""
    risk_level: str            # low | medium | high
    key_concerns: str          # comma-separated risk factors
    recommendation: str        # approve | reject | manual_review
    confidence_score: float    # 0.0 - 1.0
    reasoning: str             # LLM's explanation


class DecisionResult(BaseModel):
    """Final decision from the decision engine."""
    decision: str              # AUTO_APPROVE | AUTO_REJECT | MANUAL_REVIEW
    reason: str
    risk_level: str
    confidence_score: float

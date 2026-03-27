import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    applications: Mapped[list["LoanApplication"]] = relationship(back_populates="submitted_by_user", lazy="select")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="actor_user", lazy="select")

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Applicant info
    applicant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Loan details
    loan_amount: Mapped[float] = mapped_column(Float, nullable=False)
    loan_purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Financial profile
    employment_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    annual_income: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    credit_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    existing_debt: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    debt_to_income_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    loan_to_income_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Document
    pdf_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status: pending | processing | auto_approved | auto_rejected | manual_review | manually_approved | manually_rejected
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)

    # AI pipeline results
    risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    risk_assessment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_concerns: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    similarity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Decision
    decision: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Vector tracking
    is_embedded: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Who submitted
    submitted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    submitted_by_user: Mapped[Optional["User"]] = relationship(back_populates="applications")

    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="application", lazy="select", order_by="AuditLog.created_at")

    def __repr__(self) -> str:
        return f"<LoanApplication {self.id} [{self.status}]>"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application: Mapped["LoanApplication"] = relationship(back_populates="audit_logs")

    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    actor_user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} on {self.application_id}>"

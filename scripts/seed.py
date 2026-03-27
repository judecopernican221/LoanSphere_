"""
Seed the database with users and sample loan applications.

Usage:
    cd loan-system
    python scripts/seed.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal, create_tables
from app.core.security import hash_password
from app.core.logging import setup_logging, get_logger
from app.models.database import User, LoanApplication, AuditLog

setup_logging()
logger = get_logger(__name__)

USERS = [
    {"username": "admin",     "email": "admin@loan.com",     "password": "admin123",  "role": "admin"},
    {"username": "engineer1", "email": "engineer1@loan.com", "password": "eng123",    "role": "engineer"},
    {"username": "viewer1",   "email": "viewer1@loan.com",   "password": "view123",   "role": "viewer"},
]

APPLICATIONS = [
    {
        "applicant_name": "Rahul Sharma",   "email": "rahul@example.com",
        "loan_amount": 500_000,             "loan_purpose": "Home renovation",
        "employment_type": "salaried",      "annual_income": 1_200_000,
        "credit_score": 750,                "existing_debt": 100_000,
        "status": "auto_approved",          "risk_level": "low",
        "decision": "AUTO_APPROVE",         "confidence_score": 0.92,
        "decision_reason": "Low risk — strong credit score and healthy DTI.",
    },
    {
        "applicant_name": "Priya Mehta",    "email": "priya@example.com",
        "loan_amount": 2_000_000,           "loan_purpose": "Business expansion",
        "employment_type": "self_employed", "annual_income": 800_000,
        "credit_score": 580,                "existing_debt": 600_000,
        "status": "auto_rejected",          "risk_level": "high",
        "decision": "AUTO_REJECT",          "confidence_score": 0.88,
        "decision_reason": "High DTI 75% and credit score below 600.",
    },
    {
        "applicant_name": "Arjun Patel",    "email": "arjun@example.com",
        "loan_amount": 750_000,             "loan_purpose": "Higher education abroad",
        "employment_type": "salaried",      "annual_income": 900_000,
        "credit_score": 660,                "existing_debt": 200_000,
        "status": "manual_review",          "risk_level": "medium",
        "decision": "MANUAL_REVIEW",        "confidence_score": 0.71,
        "decision_reason": "Medium risk — borderline credit score, requires human review.",
    },
    {
        "applicant_name": "Sneha Iyer",     "email": "sneha@example.com",
        "loan_amount": 300_000,             "loan_purpose": "Medical emergency",
        "employment_type": "salaried",      "annual_income": 600_000,
        "credit_score": 720,                "existing_debt": 50_000,
        "status": "auto_approved",          "risk_level": "low",
        "decision": "AUTO_APPROVE",         "confidence_score": 0.89,
        "decision_reason": "Low risk — good credit and low loan amount.",
    },
    {
        "applicant_name": "Vikram Singh",   "email": "vikram@example.com",
        "loan_amount": 3_500_000,           "loan_purpose": "Real estate investment",
        "employment_type": "business",      "annual_income": 1_500_000,
        "credit_score": 540,                "existing_debt": 1_200_000,
        "status": "auto_rejected",          "risk_level": "high",
        "decision": "AUTO_REJECT",          "confidence_score": 0.91,
        "decision_reason": "Credit score 540 below minimum. High DTI 80%.",
    },
]


async def seed():
    await create_tables()
    print("\n🌱 Seeding database...\n")

    async with AsyncSessionLocal() as db:
        # ── Users ──────────────────────────────────────────────────────────
        user_map = {}
        for u in USERS:
            r = await db.execute(select(User).where(User.username == u["username"]))
            existing = r.scalar_one_or_none()
            if existing:
                print(f"   ⏭  User '{u['username']}' already exists")
                user_map[u["username"]] = existing
                continue
            user = User(
                username=u["username"], email=u["email"],
                hashed_password=hash_password(u["password"]), role=u["role"],
            )
            db.add(user)
            await db.flush()
            user_map[u["username"]] = user
            print(f"   ✅ Created user: {u['username']} ({u['role']})")

        engineer = user_map["engineer1"]

        # ── Applications ───────────────────────────────────────────────────
        for a in APPLICATIONS:
            r = await db.execute(select(LoanApplication).where(LoanApplication.email == a["email"]))
            if r.scalar_one_or_none():
                print(f"   ⏭  Application for '{a['email']}' already exists")
                continue

            income = a["annual_income"]
            debt   = a["existing_debt"]
            amount = a["loan_amount"]
            dti = round(debt / income, 4) if income else None
            lti = round(amount / income, 4) if income else None

            app_obj = LoanApplication(
                applicant_name=a["applicant_name"],  email=a["email"],
                loan_amount=amount,                  loan_purpose=a["loan_purpose"],
                employment_type=a["employment_type"], annual_income=income,
                credit_score=a["credit_score"],      existing_debt=debt,
                debt_to_income_ratio=dti,            loan_to_income_ratio=lti,
                status=a["status"],                  risk_level=a["risk_level"],
                decision=a["decision"],              confidence_score=a["confidence_score"],
                decision_reason=a["decision_reason"], is_embedded=False,
                submitted_by=engineer.id,
            )
            db.add(app_obj)
            await db.flush()

            db.add(AuditLog(application_id=app_obj.id, action="APPLICATION_SUBMITTED",
                details=f"Seeded: ₹{amount:,.0f}", actor=engineer.username, actor_user_id=engineer.id))
            db.add(AuditLog(application_id=app_obj.id, action="DECISION_MADE",
                details=f"{a['decision']} | Risk: {a['risk_level']}", actor="system"))
            print(f"   ✅ Created application: {a['applicant_name']} → {a['decision']}")

        await db.commit()

    print("\n✅ Seed complete!")
    print("\n   Login credentials:")
    print("   ─────────────────────────────────────────")
    for u in USERS:
        print(f"   {u['role']:10} | username: {u['username']:12} | password: {u['password']}")
    print("   ─────────────────────────────────────────\n")


if __name__ == "__main__":
    asyncio.run(seed())

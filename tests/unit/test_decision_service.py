import pytest
from unittest.mock import MagicMock
from app.services.decision_service import make_decision
from app.models.schemas import RAGAssessment


def mock_app(credit=750, dti=0.30, lti=2.5, employment="salaried"):
    """Create a mock application object for testing."""
    app = MagicMock()
    app.id = "test-uuid-1234"
    app.credit_score = credit
    app.debt_to_income_ratio = dti
    app.loan_to_income_ratio = lti
    app.employment_type = employment
    return app


def low_risk_assessment(conf=0.90):
    return RAGAssessment(
        risk_level="low", key_concerns="none",
        recommendation="approve", confidence_score=conf, reasoning="Good profile."
    )

def high_risk_assessment(conf=0.90):
    return RAGAssessment(
        risk_level="high", key_concerns="bad credit",
        recommendation="reject", confidence_score=conf, reasoning="Risky."
    )

def medium_risk_assessment(conf=0.75):
    return RAGAssessment(
        risk_level="medium", key_concerns="borderline dti",
        recommendation="manual_review", confidence_score=conf, reasoning="Borderline."
    )


class TestAutoApprove:
    def test_perfect_profile_auto_approved(self):
        app = mock_app(credit=750, dti=0.30, lti=2.5)
        result = make_decision(app, low_risk_assessment(conf=0.90))
        assert result.decision == "AUTO_APPROVE"

    def test_exactly_at_credit_threshold(self):
        app = mock_app(credit=700, dti=0.35, lti=4.0)
        result = make_decision(app, low_risk_assessment(conf=0.85))
        assert result.decision == "AUTO_APPROVE"

    def test_low_confidence_prevents_auto_approve(self):
        app = mock_app(credit=800, dti=0.20, lti=2.0)
        result = make_decision(app, low_risk_assessment(conf=0.70))  # below 0.80 threshold
        assert result.decision != "AUTO_APPROVE"

    def test_high_dti_prevents_auto_approve(self):
        app = mock_app(credit=780, dti=0.50, lti=3.0)  # DTI 50% > 40%
        result = make_decision(app, low_risk_assessment(conf=0.90))
        assert result.decision != "AUTO_APPROVE"


class TestAutoReject:
    def test_low_credit_high_risk_rejected(self):
        app = mock_app(credit=550, dti=0.70, lti=8.0)
        result = make_decision(app, high_risk_assessment(conf=0.90))
        assert result.decision == "AUTO_REJECT"

    def test_high_dti_high_risk_rejected(self):
        app = mock_app(credit=580, dti=0.75, lti=6.0)
        result = make_decision(app, high_risk_assessment(conf=0.85))
        assert result.decision == "AUTO_REJECT"

    def test_high_risk_low_confidence_goes_to_review(self):
        # Low confidence means we're not sure — send to human
        app = mock_app(credit=550, dti=0.70, lti=8.0)
        result = make_decision(app, high_risk_assessment(conf=0.60))
        assert result.decision == "MANUAL_REVIEW"


class TestManualReview:
    def test_medium_risk_goes_to_review(self):
        app = mock_app(credit=670, dti=0.45, lti=4.0)
        result = make_decision(app, medium_risk_assessment())
        assert result.decision == "MANUAL_REVIEW"

    def test_borderline_credit_goes_to_review(self):
        app = mock_app(credit=620, dti=0.38, lti=3.0)
        result = make_decision(app, medium_risk_assessment(conf=0.75))
        assert result.decision == "MANUAL_REVIEW"

    def test_reason_is_populated(self):
        app = mock_app(credit=650, dti=0.45, lti=4.0)
        result = make_decision(app, medium_risk_assessment())
        assert len(result.reason) > 10

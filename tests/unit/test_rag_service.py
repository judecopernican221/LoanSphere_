import pytest
from unittest.mock import MagicMock, patch
from app.services.rag_service import _rule_based_assessment, _parse_llm_response


def mock_app(credit=720, dti=0.35, lti=3.0, employment="salaried", income=1_000_000, amount=500_000, debt=100_000):
    app = MagicMock()
    app.id = "test-1234"
    app.applicant_name = "Test User"
    app.loan_amount = amount
    app.loan_purpose = "Home renovation"
    app.employment_type = employment
    app.annual_income = income
    app.credit_score = credit
    app.existing_debt = debt
    app.debt_to_income_ratio = dti
    app.loan_to_income_ratio = lti
    return app


class TestRuleBasedFallback:
    def test_good_profile_low_risk(self):
        app = mock_app(credit=780, dti=0.25, lti=2.0)
        result = _rule_based_assessment(app)
        assert result.risk_level == "low"
        assert result.recommendation == "approve"
        assert result.confidence_score > 0.7

    def test_bad_credit_high_risk(self):
        app = mock_app(credit=540, dti=0.70)
        result = _rule_based_assessment(app)
        assert result.risk_level == "high"
        assert result.recommendation == "reject"
        assert "credit score" in result.key_concerns

    def test_borderline_medium_risk(self):
        app = mock_app(credit=660, dti=0.45)
        result = _rule_based_assessment(app)
        assert result.risk_level == "medium"
        assert result.recommendation == "manual_review"

    def test_high_dti_flagged(self):
        app = mock_app(credit=720, dti=0.70)
        result = _rule_based_assessment(app)
        assert result.risk_level == "high"


class TestLLMResponseParsing:
    def test_valid_json_parsed(self):
        raw = '''{"risk_level": "low", "key_concerns": "none", "recommendation": "approve", "confidence_score": 0.88, "reasoning": "Good profile."}'''
        result = _parse_llm_response(raw)
        assert result is not None
        assert result.risk_level == "low"
        assert result.confidence_score == 0.88

    def test_markdown_fences_stripped(self):
        raw = '```json\n{"risk_level": "medium", "key_concerns": "high dti", "recommendation": "manual_review", "confidence_score": 0.75, "reasoning": "OK."}\n```'
        result = _parse_llm_response(raw)
        assert result is not None
        assert result.risk_level == "medium"

    def test_invalid_json_returns_none(self):
        result = _parse_llm_response("This is not JSON at all")
        assert result is None

    def test_confidence_clamped_to_0_1(self):
        raw = '{"risk_level": "low", "key_concerns": "none", "recommendation": "approve", "confidence_score": 1.5, "reasoning": "test"}'
        result = _parse_llm_response(raw)
        assert result.confidence_score <= 1.0

    def test_invalid_risk_level_returns_none(self):
        raw = '{"risk_level": "unknown_value", "key_concerns": "x", "recommendation": "approve", "confidence_score": 0.8, "reasoning": "x"}'
        result = _parse_llm_response(raw)
        assert result is None

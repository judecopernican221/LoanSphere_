"""
Embedding Service
─────────────────
Converts loan application text into 384-dimensional vectors
and stores/retrieves them from Qdrant.

Uses all-MiniLM-L6-v2 (SentenceTransformers) for embeddings.
Falls back to a simple numpy random vector if torch is not installed
(for dev/testing without GPU/large disk).
"""
import uuid
from typing import Optional
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Lazy-loaded globals — model is loaded once on first use
_embedding_model = None
_qdrant_client = None


def _get_embedding_model():
    """Load the embedding model once and cache it."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("loading_embedding_model", model=settings.EMBEDDING_MODEL)
            _embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)
            logger.info("embedding_model_loaded")
        except ImportError:
            logger.warning("sentence_transformers_not_installed_using_mock")
            _embedding_model = "mock"
    return _embedding_model


def _get_qdrant():
    """Get Qdrant client, create collection if not exists."""
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        _qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)

        # Create collection if it doesn't exist
        existing = [c.name for c in _qdrant_client.get_collections().collections]
        if settings.QDRANT_COLLECTION not in existing:
            _qdrant_client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors_config=VectorParams(
                    size=settings.EMBEDDING_DIMENSION,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("qdrant_collection_created", name=settings.QDRANT_COLLECTION)

    return _qdrant_client


def build_application_text(application) -> str:
    """
    Convert a LoanApplication into a structured text representation.
    This text is what gets embedded into a vector.

    The format is consistent so that similar applications produce
    similar embeddings — credit score band, income bracket, purpose
    all influence the resulting vector direction.
    """
    credit_band = (
        "excellent" if application.credit_score >= 750 else
        "good"      if application.credit_score >= 700 else
        "fair"      if application.credit_score >= 650 else
        "poor"      if application.credit_score >= 600 else
        "very_poor"
    )

    loan_band = (
        "small"      if application.loan_amount < 300_000 else
        "medium"     if application.loan_amount < 1_000_000 else
        "large"      if application.loan_amount < 5_000_000 else
        "very_large"
    )

    dti_pct = round((application.debt_to_income_ratio or 0) * 100, 1)
    lti = round(application.loan_to_income_ratio or 0, 2)

    text = (
        f"Loan application: {loan_band} loan of {application.loan_amount:,.0f} rupees. "
        f"Purpose: {application.loan_purpose or 'not specified'}. "
        f"Employment: {application.employment_type}. "
        f"Annual income: {application.annual_income:,.0f} rupees. "
        f"Credit score: {application.credit_score} ({credit_band}). "
        f"Debt-to-income ratio: {dti_pct}%. "
        f"Loan-to-income ratio: {lti}x. "
        f"Existing debt: {application.existing_debt:,.0f} rupees."
    )
    return text


def embed_text(text: str) -> list[float]:
    """Convert text to a 384-dimensional float vector."""
    model = _get_embedding_model()

    if model == "mock":
        # Deterministic mock embedding for dev/testing (no torch needed)
        rng = np.random.default_rng(seed=hash(text) % (2**32))
        vec = rng.standard_normal(settings.EMBEDDING_DIMENSION).astype(np.float32)
        vec = vec / np.linalg.norm(vec)  # normalize to unit vector
        return vec.tolist()

    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def upsert_application_vector(application, outcome: Optional[str] = None) -> bool:
    """
    Store (or update) a loan application's embedding in Qdrant.
    Uses the application UUID as the point ID — idempotent.
    """
    try:
        from qdrant_client.models import PointStruct

        client = _get_qdrant()
        text = build_application_text(application)
        vector = embed_text(text)

        credit_band = (
            "excellent" if (application.credit_score or 0) >= 750 else
            "good"      if (application.credit_score or 0) >= 700 else
            "fair"      if (application.credit_score or 0) >= 650 else
            "poor"      if (application.credit_score or 0) >= 600 else
            "very_poor"
        )

        payload = {
            "application_id": str(application.id),
            "credit_score_band": credit_band,
            "employment_type": application.employment_type or "unknown",
            "loan_amount": application.loan_amount,
            "loan_purpose": application.loan_purpose or "",
            "outcome": outcome or application.decision or "unknown",
            "risk_level": application.risk_level or "unknown",
        }

        client.upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=[PointStruct(
                id=str(application.id),
                vector=vector,
                payload=payload,
            )],
        )

        logger.info("vector_upserted", application_id=str(application.id))
        return True

    except Exception as e:
        logger.error("vector_upsert_failed", application_id=str(application.id), error=str(e))
        return False


def search_similar_applications(application, limit: int = 5) -> list[dict]:
    """
    Find the most similar past applications using cosine similarity.
    Filters by the same employment_type for better context relevance.
    Returns a list of payload dicts from matched points.
    """
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = _get_qdrant()
        text = build_application_text(application)
        vector = embed_text(text)

        # Optional filter: same employment type gives more relevant context
        search_filter = None
        if application.employment_type:
            search_filter = Filter(
                must=[FieldCondition(
                    key="employment_type",
                    match=MatchValue(value=application.employment_type),
                )]
            )

        results = client.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=vector,
            limit=limit,
            query_filter=search_filter,
            with_payload=True,
        )

        # Exclude the application itself (if it was already stored)
        similar = [
            {"score": r.score, **r.payload}
            for r in results
            if r.payload.get("application_id") != str(application.id)
        ]

        logger.info("similarity_search_done", found=len(similar), application_id=str(application.id))
        return similar[:limit]

    except Exception as e:
        logger.error("similarity_search_failed", application_id=str(application.id), error=str(e))
        return []

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from .env via pydantic-settings.
    Fields marked with Field(...) are required and have no fallback.
    """

    # App info
    APP_NAME: str = "Smart Loan Processing System"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="development")
    DEBUG: bool = Field(default=False)

    # Database — both async (SQLAlchemy) and sync (Alembic) URLs required
    DATABASE_URL: str = Field(...)
    DATABASE_URL_SYNC: str = Field(...)

    # Redis — used as Celery broker and result backend
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # Qdrant vector store
    QDRANT_HOST: str = Field(default="localhost")
    QDRANT_PORT: int = Field(default=6333)
    QDRANT_COLLECTION: str = Field(default="loan_applications")

    # Groq LLM
    GROQ_API_KEY: str = Field(default="")
    GROQ_MODEL: str = Field(default="llama3-8b-8192")
    GROQ_TEMPERATURE: float = Field(default=0.1)

    # JWT — SECRET_KEY must be set in .env, never rely on a default
    SECRET_KEY: str = Field(...)
    ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60)

    # Decision engine thresholds
    SIMILARITY_THRESHOLD: float = Field(default=0.75)
    CONFIDENCE_THRESHOLD: float = Field(default=0.80)
    AUTO_APPROVE_MIN_CREDIT: int = Field(default=700)
    AUTO_APPROVE_MAX_DTI: float = Field(default=0.40)
    AUTO_APPROVE_MAX_LTI: float = Field(default=5.0)
    AUTO_REJECT_MAX_CREDIT: int = Field(default=600)
    AUTO_REJECT_MIN_DTI: float = Field(default=0.65)

    # Sentence-Transformers embedding model
    EMBEDDING_MODEL: str = Field(default="all-MiniLM-L6-v2")
    EMBEDDING_DIMENSION: int = Field(default=384)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()

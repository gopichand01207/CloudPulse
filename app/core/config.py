"""
CloudPulse application configuration.
All values are loaded from environment variables or a .env file.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_NAME: str = "CloudPulse"
    VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://cloudpulse:cloudpulse@localhost:5432/cloudpulse",
        description="Async PostgreSQL connection string (asyncpg driver).",
    )

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for caching and pub/sub.",
    )

    # ------------------------------------------------------------------
    # AWS
    # ------------------------------------------------------------------
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # ------------------------------------------------------------------
    # Email / SMTP
    # ------------------------------------------------------------------
    ALERT_EMAIL: str = "alerts@example.com"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""

    # ------------------------------------------------------------------
    # Slack
    # ------------------------------------------------------------------
    SLACK_WEBHOOK_URL: str = ""

    # ------------------------------------------------------------------
    # Metrics collection
    # ------------------------------------------------------------------
    METRICS_COLLECTION_INTERVAL: int = Field(
        default=30,
        ge=5,
        description="Interval in seconds between metric collection cycles.",
    )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    LOG_LEVEL: str = "INFO"


settings = Settings()

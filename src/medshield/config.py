"""Application settings and environment validation."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_url: str = Field(default="sqlite:///./medshield.db", alias="DATABASE_URL")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_secret_key: str = Field(default="medshield-secret-key-default-2026", alias="API_SECRET_KEY")

    agent_seed_commander: str = Field(
        default="medshield_incident_commander_seed_phrase_demo_2026",
        alias="AGENT_SEED_COMMANDER"
    )
    agent_port_commander: int = Field(default=8001, alias="AGENT_PORT_COMMANDER")
    agentverse_api_key: str = Field(default="", alias="AGENTVERSE_API_KEY")
    agent_mailbox_key: str = Field(default="", alias="AGENT_MAILBOX_KEY")

    simulator_allow_actions: bool = Field(default=True, alias="SIMULATOR_ALLOW_ACTIONS")
    simulator_tick_rate_ms: int = Field(default=500, alias="SIMULATOR_TICK_RATE_MS")

    approval_signing_secret: str = Field(
        default="secure-incident-approval-hmac-key-2026",
        alias="APPROVAL_SIGNING_SECRET"
    )
    approval_expiry_seconds: int = Field(default=300, alias="APPROVAL_EXPIRY_SECONDS")

    payment_sandbox_mode: bool = Field(default=True, alias="PAYMENT_SANDBOX_MODE")
    payment_max_institutional_limit: float = Field(default=25000.0, alias="PAYMENT_MAX_INSTITUTIONAL_LIMIT")
    payment_currency: str = Field(default="USD", alias="PAYMENT_CURRENCY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

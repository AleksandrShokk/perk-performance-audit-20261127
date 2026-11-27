from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from pydantic import (
    AwareDatetime,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    public_registration_enabled: bool = True
    registration_open_until: AwareDatetime | None = None
    registration_allowed_emails: list[EmailStr] = Field(default_factory=list)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5434, ge=1, le=65535)
    postgres_db: str = "perk"
    postgres_user: str = "perk_app"
    postgres_password: SecretStr | None = None
    postgres_password_file: Path = Path(".secrets/db-app-password")
    redis_host: str = "127.0.0.1"
    redis_port: int = Field(default=6381, ge=1, le=65535)
    redis_password_file: Path = Path(".secrets/redis-password")
    security_file: Path = Path(".secrets/security.json")
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    cookie_secure: bool = True
    access_ttl_seconds: int = Field(default=900, ge=60, le=900)
    session_ttl_seconds: int = Field(default=604800, ge=900, le=604800)
    auth_limit_per_minute: int = Field(default=10, ge=1, le=100)
    api_limit_per_minute: int = Field(default=120, ge=10, le=1000)
    # Per process. API processes × (pool + overflow) plus workers must stay below
    # PostgreSQL max_connections (80 in production).
    db_pool_size: int = Field(default=5, ge=1, le=30)
    db_pool_overflow: int = Field(default=5, ge=0, le=30)
    # Requests slower than this are logged with their route and DB/crypto split.
    slow_request_ms: int = Field(default=1000, ge=50, le=60000)
    wb_service_id: str | None = None
    # Explicit private-beta exception; empty by default and expires automatically.
    wb_personal_token_test_all_workspaces: bool = False
    wb_personal_token_test_workspaces: list[UUID] = Field(default_factory=list)
    wb_personal_token_test_until: AwareDatetime | None = None
    # One-time code delivery. "console"/"fake" write codes to the log: development only.
    email_provider: Literal["console", "smtp"] = "console"
    team_invite_url: str = "http://localhost:8081/invite"
    account_recovery_url: str = "http://localhost:3000/recover-factor"
    email_from: str = "PERK <no-reply@perk.local>"
    smtp_host: str = "127.0.0.1"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_security: Literal["none", "starttls", "ssl"] = "none"
    smtp_username: str | None = None
    smtp_password_file: Path | None = None
    telegram_provider: Literal["disabled", "fake", "gateway"] = "fake"
    telegram_gateway_token_file: Path | None = None
    # Optional private CONNECT proxy; transport encryption is configured by deployment.
    telegram_gateway_proxy_url: str | None = None
    sms_provider: Literal["disabled", "fake"] = "fake"
    phone_country_codes: list[str] = Field(default_factory=lambda: ["7"])
    phone_otp_daily_limit: int = Field(default=500, ge=1, le=100000)
    # Notifications: Telegram bot for digests/alerts and Expo push for the mobile app.
    telegram_bot_provider: Literal["disabled", "fake", "bot"] = "fake"
    telegram_bot_token_file: Path | None = None
    telegram_bot_username: str = "perk_dev_bot"
    telegram_webhook_secret_file: Path | None = None
    push_provider: Literal["disabled", "fake", "expo"] = "fake"

    @field_validator("wb_personal_token_test_until", "registration_open_until", mode="before")
    @classmethod
    def empty_beta_deadline(cls, value):
        return None if value == "" else value

    def allows_personal_wb_token(self, workspace_id: UUID) -> bool:
        return (
            (
                self.wb_personal_token_test_all_workspaces
                or workspace_id in self.wb_personal_token_test_workspaces
            )
            and self.wb_personal_token_test_until is not None
            and datetime.now(UTC) < self.wb_personal_token_test_until
        )

    @model_validator(mode="after")
    def validate_production(self):
        if "*" in self.cors_origins or "*" in self.allowed_hosts:
            raise ValueError("Explicit origins and hosts are required")
        if any(not code.isdigit() or not 1 <= len(code) <= 3 for code in self.phone_country_codes):
            raise ValueError("Phone country codes must be 1-3 digits")
        if self.telegram_provider == "gateway" and not self.telegram_gateway_token_file:
            raise ValueError("Telegram Gateway requires TELEGRAM_GATEWAY_TOKEN_FILE")
        if self.telegram_bot_provider == "bot" and not (
            self.telegram_bot_token_file and self.telegram_webhook_secret_file
        ):
            raise ValueError("Telegram bot requires token and webhook secret files")
        if self.app_env == "production":
            if not self.account_recovery_url.startswith("https://"):
                raise ValueError("Production recovery requires an HTTPS app URL")
            if not self.team_invite_url.startswith("https://"):
                raise ValueError("Production invitations require an HTTPS app URL")
            if not self.cookie_secure or self.log_level == "DEBUG":
                raise ValueError("Production requires secure cookies and non-debug logging")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Production origins must use HTTPS")
            if "testserver" in self.allowed_hosts:
                raise ValueError("Configure production allowed hosts explicitly")
            if self.email_provider != "smtp" or self.smtp_security == "none":
                raise ValueError("Production requires encrypted SMTP for one-time codes")
            if "fake" in {
                self.telegram_provider,
                self.sms_provider,
                self.telegram_bot_provider,
                self.push_provider,
            }:
                raise ValueError("Fake code providers are not allowed in production")
        return self

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=(
                self.postgres_password.get_secret_value()
                if self.postgres_password
                else self.postgres_password_file.read_text().strip()
            ),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def redis_broker_url(self) -> str:
        password = quote(self.redis_password_file.read_text().strip(), safe="")
        return f"redis://:{password}@{self.redis_host}:{self.redis_port}/0"

    @property
    def redis_result_url(self) -> str:
        return self.redis_broker_url.rsplit("/", 1)[0] + "/1"


@lru_cache
def get_settings() -> Settings:
    return Settings()

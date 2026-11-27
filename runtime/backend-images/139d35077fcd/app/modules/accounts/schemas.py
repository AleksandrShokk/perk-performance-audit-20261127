from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, computed_field, field_validator

from app.modules.accounts.access import PERMISSIONS, ROLE_DEFAULTS
from app.modules.accounts.reporting import FEATURES, REPORTING_MARKETPLACES


class ConnectStoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=100)
    token: SecretStr = Field(min_length=30, max_length=8192)

    @field_validator("name")
    @classmethod
    def name_policy(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Введите название магазина.")
        return value


class RenameStoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def name_policy(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Введите название магазина.")
        return value


class RotateCredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=30, max_length=8192)


class OzonCredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    api_key: SecretStr = Field(min_length=16, max_length=512)

    @field_validator("api_key")
    @classmethod
    def header_value(cls, value):
        if any(ord(char) < 33 or ord(char) > 126 for char in value.get_secret_value()):
            raise ValueError("Проверьте API-ключ.")
        return value


class ConnectOzonInput(OzonCredentialInput):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def name_policy(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Введите название магазина.")
        return value


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    store_ids: list[str] | None = None


class StoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    marketplace: str
    connection_status: str
    last_checked_at: datetime | None

    @computed_field
    @property
    def reports_available(self) -> bool:
        return self.marketplace in REPORTING_MARKETPLACES

    @computed_field
    @property
    def features(self) -> list[str]:
        return list(FEATURES.get(self.marketplace, ()))


class ConnectionResponse(BaseModel):
    client_id: str | None = None
    status: str
    scopes: list[str]
    expires_at: datetime | None
    checked_at: datetime | None


class SyncResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source: str
    status: str
    records_processed: int
    created_at: datetime
    error_code: str | None


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    action: str
    success: bool
    created_at: datetime
    target_id: UUID | None


Permission = Literal[*PERMISSIONS]


class PermissionCatalogue(BaseModel):
    permissions: dict[Permission, str] = PERMISSIONS
    role_defaults: dict[str, list[Permission]] = ROLE_DEFAULTS

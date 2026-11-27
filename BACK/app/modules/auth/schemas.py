from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)

Client = Literal["mobile", "web"]
PhoneChannel = Literal["telegram", "sms"]
SecondFactorChannel = Literal["email", "telegram", "sms"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def check_password(value: SecretStr) -> SecretStr:
    password = value.get_secret_value()
    if len(set(password)) < 6 or password.lower() in {
        "password123456789",
        "qwerty1234567890",
        "1234567890123456",
    }:
        raise ValueError("Используйте более длинный и менее предсказуемый пароль.")
    return value


NewPassword = Annotated[
    SecretStr, Field(min_length=15, max_length=128), AfterValidator(check_password)
]


class RegisterInput(InputModel):
    email: EmailStr
    password: NewPassword
    workspace_name: str = Field(default="Команда", max_length=100)
    invite_code: str | None = Field(default=None, min_length=20, max_length=100)
    client: Client = "mobile"

    @field_validator("workspace_name")
    @classmethod
    def workspace_name_policy(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Введите название кабинета.")
        return value


class ChallengeInput(InputModel):
    challenge_id: UUID


class RegisterVerifyInput(ChallengeInput):
    code: SecretStr = Field(min_length=6, max_length=6)
    client: Client = "mobile"


class LoginInput(InputModel):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)
    client: Client = "mobile"


class RefreshInput(InputModel):
    refresh_token: SecretStr | None = Field(default=None, max_length=100)


class SendCodeInput(InputModel):
    channel: SecondFactorChannel | None = None


class VerifyCodeInput(InputModel):
    # 6 digits (email/Telegram/SMS/authenticator app) or a recovery code.
    code: SecretStr = Field(min_length=6, max_length=100)


class PhoneStartInput(InputModel):
    phone: str = Field(min_length=8, max_length=32)
    channel: Literal["telegram"] = "telegram"
    authorization_id: UUID | None = None


class PhoneChangeSendInput(InputModel):
    phone: str = Field(min_length=8, max_length=32)
    channel: Literal["telegram", "email"] = "telegram"


class PhoneChangeVerifyInput(ChallengeInput):
    code: SecretStr = Field(min_length=6, max_length=6)


class PhoneChangeAuthorization(BaseModel):
    authorization_id: UUID
    expires_in: int


class PhoneChannelInput(InputModel):
    channel: Literal["telegram"]


class PasswordChangeInput(InputModel):
    password: SecretStr = Field(min_length=1, max_length=128)
    new_password: NewPassword


class PasswordForgotInput(InputModel):
    email: EmailStr


class PasswordResetInput(ChallengeInput):
    code: SecretStr = Field(min_length=6, max_length=6)
    new_password: NewPassword


class ChallengeResponse(BaseModel):
    challenge_id: UUID
    channel: SecondFactorChannel
    destination: str = Field(description="Masked address or phone number.")
    expires_in: int
    resend_after: int


class SecondFactor(BaseModel):
    challenge: ChallengeResponse | None = Field(
        default=None,
        description="Absent when the user must enter an authenticator code.",
    )
    available: list[Literal["email", "telegram", "sms", "totp", "recovery"]]
    delivery_error: str | None = Field(
        default=None,
        description="The automatic code was not sent; request it via /auth/mfa/send.",
    )


class TokenResponse(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    csrf_token: str | None = None
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    mfa_required: bool
    second_factor: SecondFactor | None = None


class MeResponse(BaseModel):
    id: UUID
    email: str
    email_verified: bool
    phone: str | None = Field(description="Masked verified phone number.")
    phone_channel: PhoneChannel | None
    totp_enabled: bool
    strong_factor_enabled: bool
    session_mfa_verified: bool
    step_up_valid: bool
    strong_step_up_valid: bool
    # Kept for existing clients; equals totp_enabled or a verified phone.
    mfa_enabled: bool


class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str] | None = Field(
        description="Shown once when the first strong factor is enabled or codes are renewed."
    )


class MessageResponse(BaseModel):
    message: str


class FirstFactorCancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=46, max_length=46)

import logging
import secrets
from datetime import timedelta

import pyotp
from app.db.session import set_actor
from app.integrations.notifications import DeliveryError, mask_phone
from app.modules.accounts.models import Workspace
from app.modules.audit.service import audit
from app.modules.auth import otp, phone_change
from app.modules.auth.dependencies import (
    DB,
    CurrentIdentity,
    FullIdentity,
    RecentIdentity,
    StrongIdentity,
    fresh,
    now,
    strong_identity,
)
from app.modules.auth.models import Membership, OtpChallenge, User
from app.modules.auth.schemas import (
    ChallengeInput,
    ChallengeResponse,
    FirstFactorCancelInput,
    LoginInput,
    MeResponse,
    MessageResponse,
    MfaSetupResponse,
    PasswordChangeInput,
    PasswordForgotInput,
    PasswordResetInput,
    PhoneChangeAuthorization,
    PhoneChangeSendInput,
    PhoneChangeVerifyInput,
    PhoneChannelInput,
    PhoneStartInput,
    RecoveryCodesResponse,
    RefreshInput,
    RegisterInput,
    RegisterVerifyInput,
    SecondFactor,
    SendCodeInput,
    TokenResponse,
    VerifyCodeInput,
)
from app.modules.auth.service import (
    STRONG_METHODS,
    clear_cookies,
    create_session,
    enforce_client,
    has_recovery_codes,
    issue_tokens,
    recovery_codes,
    revoke_all,
    rotate,
    start_session,
    user_limit,
    verify_recovery,
    verify_totp,
)
from app.security.crypto import (
    DUMMY_PASSWORD_HASH,
    PASSWORD_HASHER,
    hash_password,
    verify_password,
)
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

REGISTER_EXISTS_NOTICE = (
    "Попытка регистрации в PERK",
    "Кто-то пытался зарегистрироваться в PERK с этим адресом, но аккаунт уже существует.\n"
    "Если это были вы — войдите или восстановите пароль. Если нет — проигнорируйте письмо.",
)
RESET_UNKNOWN_NOTICE = (
    "Сброс пароля PERK",
    "Кто-то запросил сброс пароля для этого адреса, но аккаунта PERK с ним нет.\n"
    "Если это были не вы, просто проигнорируйте письмо.",
)
INVALID_LOGIN = "Неверный email или пароль."


def locked_user(db, user_id):
    # NO KEY UPDATE: background inserts referencing the user (KEY SHARE) must not block auth.
    return db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )


def locked_challenge(db, challenge_id, purpose):
    return db.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.id == challenge_id, OtpChallenge.purpose == purpose)
        .with_for_update()
    )


def notify_security(request, user, text):
    """Security notices are best effort: a mail outage must not undo a committed change."""
    try:
        request.app.state.notifier.send_email(
            user.email,
            "Безопасность аккаунта PERK",
            f"{text}\n\nЕсли это были не вы, срочно смените пароль и напишите в поддержку.",
        )
    except DeliveryError:
        logger.error("security_notice_unavailable")


def default_channel(request, user):
    """Phone first; an authenticator app needs no delivery; email only without strong factors."""
    if user.totp_ciphertext:
        return None
    if user.phone_verified_at:
        channels = request.app.state.notifier.phone_channels()
        if user.phone_channel in channels:
            return user.phone_channel
        return channels[0] if channels else None
    return "email"


def available_methods(request, user):
    methods = []
    if user.phone_verified_at:
        methods += request.app.state.notifier.phone_channels()
    if user.totp_ciphertext:
        methods.append("totp")
    methods.append("recovery" if user.has_strong_factor else "email")
    return methods


def channel_destination(request, user, channel):
    if channel == "email":
        if user.has_strong_factor:
            raise otp.error(
                400,
                "channel_not_allowed",
                "Для этого аккаунта код на почту не используется. "
                "Выберите телефон, приложение или резервный код.",
            )
        return user.email
    if not user.phone_verified_at:
        raise otp.error(400, "phone_not_verified", "Сначала подтвердите номер телефона.")
    if channel not in request.app.state.notifier.phone_channels():
        raise otp.error(400, f"{channel}_unavailable", "Этот способ сейчас недоступен.")
    return user.phone


def send_factor(db, request, purpose, user, session, channel):
    destination = channel_destination(request, user, channel)
    otp.throttle(request, channel, destination)
    challenge, code = otp.prepare(
        db,
        request.app.state.vault,
        purpose=purpose,
        channel=channel,
        destination=destination,
        user_id=user.id,
        session_id=session.id,
        challenge=otp.active(db, purpose=purpose, session_id=session.id, lock=True),
    )
    db.commit()
    otp.deliver(request, purpose, channel, destination, code)
    return otp.response(challenge, destination)


def verify_second_factor(db, request, user, session, purpose, code):
    """Return the verified method or raise. Recovery codes and TOTP never need delivery."""
    vault = request.app.state.vault
    code = code.strip()
    if code.startswith("rc_"):
        if user.has_strong_factor and verify_recovery(db, vault, user, code):
            return "recovery"
        raise otp.error(400, "otp_invalid", "Неверный код.")
    challenge = otp.active(db, purpose=purpose, session_id=session.id, lock=True)
    if challenge and challenge.channel == "email" and user.has_strong_factor:
        challenge = None  # A phone/app was added after the email code was sent.
    if user.totp_ciphertext and verify_totp(user, vault, code):
        if challenge:
            challenge.consumed_at = now()
        return "totp"
    if challenge is None:
        raise otp.error(400, "otp_invalid", "Неверный код. Запросите новый.")
    otp.check(db, vault, challenge, code)
    return challenge.channel


# Registration


def require_registration(request, *, invited: bool, email: str | None = None):
    settings = request.app.state.settings
    allowed = {str(value).lower() for value in getattr(settings, "registration_allowed_emails", [])}
    permitted_email = email is not None and email.strip().lower() in allowed
    deadline = getattr(settings, "registration_open_until", None)
    public = settings.public_registration_enabled and (deadline is None or now() < deadline)
    if not public and not invited and not permitted_email:
        raise otp.error(403, "registration_closed", "Регистрация доступна только по приглашению.")


@router.post(
    "/register",
    response_model=ChallengeResponse,
    status_code=202,
    operation_id="authRegister",
)
def register(data: RegisterInput, request: Request, db: DB):
    """Always answers the same way; the account is created only after the emailed code."""
    require_registration(request, invited=bool(data.invite_code), email=str(data.email))
    enforce_client(request, data.client)
    email = str(data.email).lower()
    user_limit(request, email)
    otp.throttle(request, "email", email)
    # Hash even for an existing address so response time does not reveal registration.
    password_hash = hash_password(data.password.get_secret_value())
    exists = db.scalar(select(User.id).where(User.email == email)) is not None
    payload = {"email": email}
    if data.invite_code:
        from app.modules.accounts.team import invalid_invite, invite_details

        details = invite_details(db, request.app.state.vault, data.invite_code)
        if details["email"] != email:
            raise invalid_invite()
        payload["invited"] = True
    if not exists:
        payload |= {
            "password_hash": password_hash,
            "workspace_name": data.workspace_name,
        }
    challenge, code = otp.prepare(
        db,
        request.app.state.vault,
        purpose="register",
        channel="email",
        destination=email,
        payload=payload,
        decoy=exists,
    )
    db.commit()
    otp.deliver(
        request,
        "register",
        "email",
        email,
        code,
        notice=REGISTER_EXISTS_NOTICE if exists else None,
    )
    return otp.response(challenge, email)


@router.post(
    "/register/resend",
    response_model=ChallengeResponse,
    status_code=202,
    operation_id="authRegisterResend",
)
def register_resend(data: ChallengeInput, request: Request, db: DB):
    vault = request.app.state.vault
    challenge = locked_challenge(db, data.challenge_id, "register")
    if not challenge or challenge.consumed_at:
        raise otp.error(400, "otp_not_found", "Начните регистрацию заново.")
    payload = otp.payload(vault, challenge)
    require_registration(request, invited=bool(payload.get("invited")), email=payload["email"])
    email, decoy = payload["email"], "password_hash" not in payload
    otp.throttle(request, "email", email)
    challenge, code = otp.prepare(
        db,
        vault,
        purpose="register",
        channel="email",
        destination=email,
        challenge=challenge,
        decoy=decoy,
    )
    db.commit()
    otp.deliver(
        request,
        "register",
        "email",
        email,
        code,
        notice=REGISTER_EXISTS_NOTICE if decoy else None,
    )
    return otp.response(challenge, email)


@router.post(
    "/register/verify",
    response_model=TokenResponse,
    status_code=201,
    operation_id="authRegisterVerify",
)
def register_verify(data: RegisterVerifyInput, request: Request, response: Response, db: DB):
    enforce_client(request, data.client)
    user_limit(request, str(data.challenge_id))
    vault = request.app.state.vault
    challenge = locked_challenge(db, data.challenge_id, "register")
    otp.check(db, vault, challenge, data.code.get_secret_value())
    payload = otp.payload(vault, challenge)
    require_registration(request, invited=bool(payload.get("invited")), email=payload["email"])
    unavailable = otp.error(
        409,
        "registration_unavailable",
        "Аккаунт с этим адресом уже существует. Войдите или восстановите пароль.",
    )
    if "password_hash" not in payload or db.scalar(
        select(User.id).where(User.email == payload["email"])
    ):
        raise unavailable
    user = User(
        email=payload["email"],
        password_hash=payload["password_hash"],
        email_verified_at=now(),
    )
    db.add(user)
    try:
        db.flush()
        set_actor(db, user.id)
        workspace_id = None
        if not payload.get("invited"):
            workspace = Workspace(name=payload["workspace_name"], owner_user_id=user.id)
            db.add(workspace)
            db.flush()
            db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
            db.flush()
            workspace_id = workspace.id
        audit(db, "auth.register", user_id=user.id, workspace_id=workspace_id)
        return start_session(db, request, response, user, data.client, method="email")
    except IntegrityError:
        db.rollback()
        raise unavailable from None


# Sign in and the second factor


@router.post("/login", response_model=TokenResponse, operation_id="authLogin")
def login(data: LoginInput, request: Request, response: Response, db: DB):
    """Password step. The returned session is limited until /auth/mfa/verify succeeds."""
    enforce_client(request, data.client)
    email = str(data.email).lower()
    user_limit(request, email)
    user = db.scalar(select(User).where(User.email == email).with_for_update(key_share=True))
    valid = verify_password(
        user.password_hash if user else DUMMY_PASSWORD_HASH,
        data.password.get_secret_value(),
    )
    if not user or not valid or not user.is_active or not user.email_verified_at:
        audit(db, "auth.login_failed", success=False)
        db.commit()
        raise HTTPException(401, INVALID_LOGIN)
    set_actor(db, user.id)
    if PASSWORD_HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password.get_secret_value())
    audit(db, "auth.password_verified", user_id=user.id)
    session = create_session(db, request, user, data.client)
    channel = default_channel(request, user)
    second = SecondFactor(available=available_methods(request, user))
    delivery = None
    if channel:
        destination = channel_destination(request, user, channel)
        try:
            otp.throttle(request, channel, destination)
            challenge, code = otp.prepare(
                db,
                request.app.state.vault,
                purpose="login",
                channel=channel,
                destination=destination,
                user_id=user.id,
                session_id=session.id,
            )
            second.challenge = ChallengeResponse(**otp.response(challenge, destination))
            delivery = (channel, destination, code)
        except HTTPException:
            # Throttled: the session still works for choosing another method or retrying later.
            second.delivery_error = "otp_throttled"
    tokens = issue_tokens(db, request, response, session)
    if delivery:
        try:
            otp.deliver(request, "login", *delivery)
        except HTTPException as exc:
            second.challenge = None
            second.delivery_error = exc.detail["code"]
    tokens.second_factor = second
    return tokens


@router.post(
    "/mfa/send",
    response_model=ChallengeResponse,
    status_code=202,
    operation_id="authMfaSend",
)
def mfa_send(data: SendCodeInput, request: Request, db: DB, identity: CurrentIdentity):
    if identity.session.mfa_verified_at:
        raise otp.error(409, "already_verified", "Вход уже подтверждён.")
    channel = data.channel or default_channel(request, identity.user)
    if channel is None:
        raise otp.error(400, "use_authenticator", "Введите код из приложения-аутентификатора.")
    return send_factor(db, request, "login", identity.user, identity.session, channel)


@router.post("/mfa/verify", response_model=TokenResponse, operation_id="authMfaVerify")
def mfa_verify(
    data: VerifyCodeInput,
    request: Request,
    response: Response,
    db: DB,
    identity: CurrentIdentity,
):
    """Replaces the limited session with a new fully verified one."""
    if identity.session.mfa_verified_at:
        raise otp.error(409, "already_verified", "Вход уже подтверждён.")
    user = locked_user(db, identity.user.id)
    user_limit(request, str(user.id))
    method = verify_second_factor(
        db, request, user, identity.session, "login", data.code.get_secret_value()
    )
    identity.session.revoked_at = now()
    audit(db, "auth.login", user_id=user.id)
    return start_session(db, request, response, user, identity.session.client, method=method)


@router.post("/refresh", response_model=TokenResponse, operation_id="authRefresh")
def refresh(data: RefreshInput, request: Request, response: Response, db: DB):
    return rotate(
        db,
        request,
        response,
        data.refresh_token.get_secret_value() if data.refresh_token else None,
    )


@router.get("/me", response_model=MeResponse, operation_id="authMe")
def me(identity: CurrentIdentity):
    user, session = identity.user, identity.session
    return MeResponse(
        id=user.id,
        email=user.email,
        email_verified=bool(user.email_verified_at),
        phone=mask_phone(user.phone) if user.phone_verified_at and user.phone else None,
        phone_channel=user.phone_channel if user.phone_verified_at else None,
        totp_enabled=bool(user.totp_ciphertext),
        strong_factor_enabled=user.has_strong_factor,
        session_mfa_verified=bool(session.mfa_verified_at),
        step_up_valid=fresh(session.step_up_at),
        strong_step_up_valid=user.has_strong_factor and fresh(session.strong_step_up_at),
        mfa_enabled=user.has_strong_factor,
    )


@router.post("/logout", response_model=MessageResponse, operation_id="authLogout")
def logout(request: Request, response: Response, db: DB, identity: CurrentIdentity):
    identity.session.revoked_at = now()
    from app.modules.notifications.service import revoke_devices

    revoke_devices(db, identity.user.id, identity.session.id)
    audit(db, "auth.logout", user_id=identity.user.id)
    db.commit()
    clear_cookies(response, request.app.state.settings)
    return MessageResponse(message="Вы вышли из аккаунта.")


@router.post("/logout-all", response_model=MessageResponse, operation_id="authLogoutAll")
def logout_all(request: Request, response: Response, db: DB, identity: FullIdentity):
    """Revoking every device needs a verified session: a password alone must not lock out
    the owner. A limited session can still end itself via /auth/logout."""
    revoke_all(db, identity.user.id)
    audit(db, "auth.logout_all", user_id=identity.user.id)
    db.commit()
    clear_cookies(response, request.app.state.settings)
    return MessageResponse(message="Вход на всех устройствах завершён.")


# Confirmation before sensitive actions


@router.post(
    "/step-up/send",
    response_model=ChallengeResponse,
    status_code=202,
    operation_id="authStepUpSend",
)
def step_up_send(data: SendCodeInput, request: Request, db: DB, identity: FullIdentity):
    channel = data.channel or default_channel(request, identity.user)
    if channel is None:
        raise otp.error(400, "use_authenticator", "Введите код из приложения-аутентификатора.")
    return send_factor(db, request, "step_up", identity.user, identity.session, channel)


@router.post("/step-up/verify", response_model=MessageResponse, operation_id="authStepUpVerify")
def step_up_verify(data: VerifyCodeInput, request: Request, db: DB, identity: FullIdentity):
    user = locked_user(db, identity.user.id)
    user_limit(request, str(user.id))
    method = verify_second_factor(
        db, request, user, identity.session, "step_up", data.code.get_secret_value()
    )
    identity.session.step_up_at = now()
    if method in STRONG_METHODS:
        identity.session.strong_step_up_at = now()
    audit(db, "auth.step_up", user_id=user.id)
    db.commit()
    return MessageResponse(message="Действие подтверждено на 5 минут")


# Phone number: Telegram, with separate old-phone/email verification for replacement.


def require_strong_if_configured(identity):
    """The first strong factor may be added after email login; replacing one needs a code."""
    if identity.user.has_strong_factor:
        strong_identity(identity)


def first_strong_codes(db, request, user, was_strong):
    if not was_strong or not has_recovery_codes(db, user.id):
        return recovery_codes(db, request.app.state.vault, user.id)
    return None


@router.post(
    "/phone/change/send",
    response_model=ChallengeResponse,
    status_code=202,
    operation_id="authPhoneChangeSend",
)
def phone_change_send(data: PhoneChangeSendInput, request: Request, db: DB, identity: FullIdentity):
    user = locked_user(db, identity.user.id)
    return phone_change.send(db, request, user, identity.session, data)


@router.post(
    "/phone/change/verify",
    response_model=PhoneChangeAuthorization,
    operation_id="authPhoneChangeVerify",
)
def phone_change_verify(
    data: PhoneChangeVerifyInput, request: Request, db: DB, identity: FullIdentity
):
    user = locked_user(db, identity.user.id)
    user_limit(request, str(user.id))
    return phone_change.verify(db, request, user, identity.session, data)


@router.post(
    "/phone",
    response_model=ChallengeResponse,
    status_code=202,
    operation_id="authPhoneStart",
)
def phone_start(data: PhoneStartInput, request: Request, db: DB, identity: FullIdentity):
    user = locked_user(db, identity.user.id)
    phone = otp.normalize_phone(data.phone, request.app.state.settings.phone_country_codes)
    changing = bool(user.phone_verified_at and user.phone)
    if changing:
        phone_change.authorize(
            db,
            request.app.state.vault,
            user,
            identity.session,
            data.authorization_id,
            phone,
        )
    else:
        require_strong_if_configured(identity)
    if data.channel not in request.app.state.notifier.phone_channels():
        raise otp.error(400, f"{data.channel}_unavailable", "Этот способ сейчас недоступен.")
    otp.throttle(request, data.channel, phone)
    challenge, code = otp.prepare(
        db,
        request.app.state.vault,
        purpose="phone_verify",
        channel=data.channel,
        destination=phone,
        user_id=identity.user.id,
        session_id=identity.session.id,
        payload={
            "phone": phone,
            "channel": data.channel,
            "previous_phone": user.phone if changing else None,
            "authorization_id": str(data.authorization_id) if changing else None,
        },
        challenge=otp.active(db, purpose="phone_verify", session_id=identity.session.id, lock=True),
    )
    db.commit()
    otp.deliver(request, "phone_verify", data.channel, phone, code)
    return otp.response(challenge, phone)


@router.post(
    "/phone/confirm",
    response_model=RecoveryCodesResponse,
    operation_id="authPhoneConfirm",
)
def phone_confirm(data: VerifyCodeInput, request: Request, db: DB, identity: FullIdentity):
    user = locked_user(db, identity.user.id)
    changing = bool(user.phone_verified_at and user.phone)
    if not changing:
        require_strong_if_configured(identity)
    user_limit(request, str(user.id))
    vault = request.app.state.vault
    challenge = otp.active(db, purpose="phone_verify", session_id=identity.session.id, lock=True)
    otp.check(db, vault, challenge, data.code.get_secret_value())
    payload = otp.payload(vault, challenge)
    if payload.get("previous_phone") != (user.phone if changing else None):
        raise otp.error(403, "phone_change_required", "Номер уже изменён. Начните заново.")
    if changing:
        from uuid import UUID

        phone_change.authorize(
            db,
            vault,
            user,
            identity.session,
            UUID(payload["authorization_id"]) if payload.get("authorization_id") else None,
            payload["phone"],
        )
    in_use = otp.error(409, "phone_in_use", "Этот номер уже привязан к другому аккаунту.")
    if db.scalar(select(User.id).where(User.phone == payload["phone"], User.id != user.id)):
        raise in_use
    was_strong = user.has_strong_factor
    try:
        user.phone, user.phone_channel = payload["phone"], payload["channel"]
        user.phone_verified_at = now()
        phone_change.invalidate(
            db, user.id, purposes=("phone_change", "phone_verify", "login", "step_up")
        )
        identity.session.step_up_at = identity.session.strong_step_up_at = now()
        codes = first_strong_codes(db, request, user, was_strong)
        audit(db, "auth.phone_verified", user_id=user.id)
        if not was_strong:
            from app.modules.auth.factor_recovery import offer

            offer(request, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise in_use from None
    notify_security(request, user, f"К аккаунту привязан номер {mask_phone(user.phone)}.")
    return RecoveryCodesResponse(recovery_codes=codes)


@router.put("/phone/channel", response_model=MessageResponse, operation_id="authPhoneChannel")
def phone_channel(data: PhoneChannelInput, request: Request, db: DB, identity: StrongIdentity):
    if not identity.user.phone_verified_at:
        raise otp.error(400, "phone_not_verified", "Сначала подтвердите номер телефона.")
    if data.channel not in request.app.state.notifier.phone_channels():
        raise otp.error(400, f"{data.channel}_unavailable", "Этот способ сейчас недоступен.")
    identity.user.phone_channel = data.channel
    audit(db, "auth.phone_channel_changed", user_id=identity.user.id)
    db.commit()
    return MessageResponse(message="Способ получения кодов изменён")


# Authenticator app (optional strong factor)


@router.post("/totp/setup", response_model=MfaSetupResponse, operation_id="authTotpSetup")
def totp_setup(request: Request, db: DB, identity: FullIdentity):
    require_strong_if_configured(identity)
    user = locked_user(db, identity.user.id)
    user_limit(request, str(user.id))
    if user.totp_ciphertext:
        raise otp.error(409, "totp_enabled", "Приложение-аутентификатор уже подключено.")
    secret = pyotp.random_base32()
    user.totp_pending_ciphertext = request.app.state.vault.seal(secret, f"totp-pending:{user.id}")
    user.totp_pending_until = now() + timedelta(minutes=10)
    audit(db, "auth.mfa_setup", user_id=user.id)
    db.commit()
    return MfaSetupResponse(
        secret=secret,
        provisioning_uri=pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="PERK"),
    )


@router.post(
    "/totp/confirm",
    response_model=RecoveryCodesResponse,
    operation_id="authTotpConfirm",
)
def totp_confirm(data: VerifyCodeInput, request: Request, db: DB, identity: FullIdentity):
    require_strong_if_configured(identity)
    user = locked_user(db, identity.user.id)
    user_limit(request, str(user.id))
    if user.totp_ciphertext or not user.totp_pending_ciphertext or user.totp_pending_until <= now():
        raise otp.error(400, "totp_setup_expired", "Начните подключение заново.")
    vault = request.app.state.vault
    secret = vault.open(user.totp_pending_ciphertext, f"totp-pending:{user.id}")
    step = int(now().timestamp()) // 30
    if not secrets.compare_digest(pyotp.TOTP(secret).at(step * 30), data.code.get_secret_value()):
        raise otp.error(400, "otp_invalid", "Неверный код.")
    was_strong = user.has_strong_factor
    user.totp_ciphertext = vault.seal(secret, f"totp:{user.id}")
    user.totp_pending_ciphertext = None
    user.totp_pending_until = None
    user.totp_last_step = step
    identity.session.step_up_at = identity.session.strong_step_up_at = now()
    codes = first_strong_codes(db, request, user, was_strong)
    audit(db, "auth.mfa_enabled", user_id=user.id)
    if not was_strong:
        from app.modules.auth.factor_recovery import offer

        offer(request, user)
    db.commit()
    notify_security(request, user, "К аккаунту подключено приложение-аутентификатор.")
    return RecoveryCodesResponse(recovery_codes=codes)


@router.delete("/totp", response_model=MessageResponse, operation_id="authTotpDisable")
def totp_disable(request: Request, db: DB, identity: StrongIdentity):
    user = locked_user(db, identity.user.id)
    user.totp_ciphertext = None
    user.totp_pending_ciphertext = None
    user.totp_pending_until = None
    user.totp_last_step = None
    audit(db, "auth.mfa_disabled", user_id=user.id)
    db.commit()
    notify_security(request, user, "Приложение-аутентификатор отключено.")
    return MessageResponse(message="Приложение-аутентификатор отключено")


@router.post(
    "/recovery-codes",
    response_model=RecoveryCodesResponse,
    operation_id="authRecoveryCodes",
)
def renew_recovery_codes(request: Request, db: DB, identity: StrongIdentity):
    codes = recovery_codes(db, request.app.state.vault, identity.user.id)
    audit(db, "auth.recovery_codes_renewed", user_id=identity.user.id)
    db.commit()
    return RecoveryCodesResponse(recovery_codes=codes)


# Password


@router.post("/password", response_model=MessageResponse, operation_id="authChangePassword")
def change_password(
    data: PasswordChangeInput,
    request: Request,
    response: Response,
    db: DB,
    identity: RecentIdentity,
):
    user = locked_user(db, identity.user.id)
    user_limit(request, str(user.id))
    if not verify_password(user.password_hash, data.password.get_secret_value()):
        raise otp.error(400, "password_invalid", "Неверный текущий пароль.")
    user.password_hash = hash_password(data.new_password.get_secret_value())
    revoke_all(db, user.id)
    audit(db, "auth.password_changed", user_id=user.id)
    db.commit()
    clear_cookies(response, request.app.state.settings)
    notify_security(request, user, "Пароль от аккаунта изменён.")
    return MessageResponse(message="Пароль изменён. Войдите снова.")


@router.post(
    "/password/forgot",
    response_model=ChallengeResponse,
    status_code=202,
    operation_id="authPasswordForgot",
)
def password_forgot(data: PasswordForgotInput, request: Request, db: DB):
    """Same answer for unknown addresses. A reset never bypasses the phone/app factor."""
    email = str(data.email).lower()
    user_limit(request, email)
    otp.throttle(request, "email", email)
    user = db.scalar(select(User).where(User.email == email))
    exists = bool(user and user.is_active and user.email_verified_at)
    challenge, code = otp.prepare(
        db,
        request.app.state.vault,
        purpose="password_reset",
        channel="email",
        destination=email,
        user_id=user.id if exists else None,
        payload={"email": email},
        decoy=not exists,
    )
    db.commit()
    otp.deliver(
        request,
        "password_reset",
        "email",
        email,
        code,
        notice=None if exists else RESET_UNKNOWN_NOTICE,
    )
    return otp.response(challenge, email)


@router.post("/password/reset", response_model=MessageResponse, operation_id="authPasswordReset")
def password_reset(data: PasswordResetInput, request: Request, response: Response, db: DB):
    user_limit(request, str(data.challenge_id))
    challenge = locked_challenge(db, data.challenge_id, "password_reset")
    otp.check(db, request.app.state.vault, challenge, data.code.get_secret_value())
    user = locked_user(db, challenge.user_id) if challenge.user_id else None
    if not user or not user.is_active:
        raise otp.error(400, "otp_invalid", "Неверный код.")
    set_actor(db, user.id)
    user.password_hash = hash_password(data.new_password.get_secret_value())
    revoke_all(db, user.id)
    audit(db, "auth.password_reset", user_id=user.id)
    db.commit()
    clear_cookies(response, request.app.state.settings)
    notify_security(request, user, "Пароль от аккаунта сброшен по коду из письма.")
    return MessageResponse(message="Пароль изменён. Войдите с новым паролем.")


@router.post(
    "/factor/cancel",
    response_model=MessageResponse,
    operation_id="authCancelFirstFactor",
)
def cancel_first_factor(data: FirstFactorCancelInput, request: Request, db: DB):
    from app.modules.auth.factor_recovery import cancel

    cancel(request, db, data.token.get_secret_value())
    return MessageResponse(message="Подключение отменено. Войдите заново и смените пароль.")

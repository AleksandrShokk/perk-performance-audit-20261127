"""Delivery of one-time codes. Fixed provider endpoints; no code or address in error logs."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

import httpx
from app.integrations.email_templates import render_email

logger = logging.getLogger("perk.notifications")
TELEGRAM_SEND_URL = "https://gatewayapi.telegram.org/sendVerificationMessage"


class DeliveryError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def mask_email(value: str) -> str:
    name, _, domain = value.partition("@")
    return (name[:1] or "*") + "***@" + domain


def mask_phone(value: str) -> str:
    return value[:2] + " *** ***-" + value[-4:-2] + "-" + value[-2:]


class ConsoleEmail:
    def send(self, to: str, subject: str, body: str, *, html: str | None = None) -> None:
        # Local development only; production settings forbid this provider.
        logger.warning("dev_email to=%s subject=%s\n%s", to, subject, body)


class SmtpEmail:
    def __init__(self, settings):
        self.settings = settings
        self.password = (
            Path(settings.smtp_password_file).read_text(encoding="utf-8").strip()
            if settings.smtp_password_file
            else None
        )

    def send(self, to: str, subject: str, body: str, *, html: str | None = None) -> None:
        s = self.settings
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = s.email_from, to, subject
        message.set_content(body)
        message.add_alternative(html or render_email(subject, body), subtype="html")
        context = ssl.create_default_context()
        try:
            if s.smtp_security == "ssl":
                client = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=10, context=context)
            else:
                client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10)
            with client:
                if s.smtp_security == "starttls":
                    client.starttls(context=context)
                if s.smtp_username:
                    client.login(s.smtp_username, self.password or "")
                client.send_message(message)
        except smtplib.SMTPException, OSError:
            logger.error("email_delivery_failed")
            raise DeliveryError("email_unavailable") from None


class FakePhone:
    def __init__(self, channel: str):
        self.channel = channel

    def send(self, phone: str, code: str, ttl: int) -> None:
        logger.warning("dev_%s_code to=%s code=%s", self.channel, mask_phone(phone), code)


class TelegramGateway:
    def __init__(self, token_file: Path, transport=None, *, proxy=None):
        self.token = Path(token_file).read_text(encoding="utf-8").strip()
        self.transport = transport
        self.proxy = proxy or None

    def send(self, phone: str, code: str, ttl: int) -> None:
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10, connect=3),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
                proxy=self.proxy,
            ) as client:
                response = client.post(
                    TELEGRAM_SEND_URL,
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={"phone_number": phone, "code": code, "ttl": ttl},
                )
            if len(response.content) > 65536:
                raise ValueError
            data = response.json()
        except httpx.HTTPError, ValueError:
            logger.error("telegram_delivery_unavailable")
            raise DeliveryError("telegram_unavailable") from None
        if not isinstance(data, dict) or data.get("ok") is not True:
            # The provider error name contains no secret; it helps distinguish bad tokens.
            error = data.get("error") if isinstance(data, dict) else None
            logger.error("telegram_delivery_rejected error=%s", str(error)[:64])
            raise DeliveryError("telegram_unavailable")


TELEGRAM_BOT_URL = "https://api.telegram.org/bot{token}/sendMessage"
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def post_json(url, payload, *, headers=None, transport=None, code):
    try:
        with httpx.Client(
            timeout=httpx.Timeout(10, connect=3),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            response = client.post(url, json=payload, headers=headers or {})
        if len(response.content) > 262144:
            raise ValueError
        data = response.json()
    except httpx.HTTPError, ValueError:
        raise DeliveryError(code) from None
    return response.status_code, data


class FakeMessenger:
    def send_notifications(self, tokens, title, body, data, **options):
        self.send_push(tokens, title, body, data)
        return [{"status": "ok", "id": "dev-" + str(index)} for index, _ in enumerate(tokens)]

    def get_receipts(self, identifiers):
        return {key: {"status": "ok"} for key in identifiers}

    """Development: messages go to the log instead of Telegram or phones."""

    def send_message(self, chat_id: str, text: str) -> None:
        logger.warning("dev_telegram_message chat=%s\n%s", str(chat_id)[-4:], text)

    def send_push(self, tokens: list[str], title: str, body: str, data: dict) -> list[str]:
        logger.warning("dev_push devices=%s title=%s", len(tokens), title)
        return []


class TelegramBot:
    def __init__(self, token_file: Path, transport=None):
        self.token = Path(token_file).read_text(encoding="utf-8").strip()
        self.transport = transport

    def send_message(self, chat_id: str, text: str) -> None:
        status, data = post_json(
            TELEGRAM_BOT_URL.format(token=self.token),
            {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True},
            transport=self.transport,
            code="telegram_bot_unavailable",
        )
        if status != 200 or not isinstance(data, dict) or data.get("ok") is not True:
            logger.error("telegram_bot_rejected status=%s", status)
            raise DeliveryError("telegram_bot_unavailable")


class ExpoPush:
    def __init__(self, transport=None):
        self.transport = transport

    def send_notifications(self, tokens, title, body, data, *, channel, category):
        """One ticket per device. A malformed response is never treated as success."""
        tickets = []
        for offset in range(0, len(tokens), 100):
            batch = tokens[offset : offset + 100]
            messages = [
                {
                    "to": token,
                    "title": title[:100],
                    "body": body[:500],
                    "data": data,
                    "sound": "default",
                    "channelId": channel,
                    "categoryId": category,
                    "priority": "high",
                    "ttl": 3600,
                }
                for token in batch
            ]
            status, result = post_json(
                EXPO_PUSH_URL, messages, transport=self.transport, code="push_unavailable"
            )
            rows = result.get("data") if isinstance(result, dict) else None
            if status != 200 or not isinstance(rows, list) or len(rows) != len(batch):
                raise DeliveryError("push_unavailable")
            for row in rows:
                if not isinstance(row, dict) or row.get("status") not in {"ok", "error"}:
                    raise DeliveryError("push_unavailable")
                if row["status"] == "ok" and (
                    not isinstance(row.get("id"), str) or not row["id"] or len(row["id"]) > 200
                ):
                    raise DeliveryError("push_unavailable")
                if row["status"] == "error" and not isinstance(row.get("details", {}), dict):
                    raise DeliveryError("push_unavailable")
            tickets.extend(rows)
        return tickets

    def send_push(self, tokens, title, body, data):
        tickets = self.send_notifications(
            tokens, title, body, data, channel="perk_updates", category="perk_open"
        )
        return [
            token
            for token, row in zip(tokens, tickets, strict=True)
            if row.get("details", {}).get("error") == "DeviceNotRegistered"
        ]

    def get_receipts(self, identifiers):
        if not identifiers:
            return {}
        status, result = post_json(
            "https://exp.host/--/api/v2/push/getReceipts",
            {"ids": identifiers[:1000]},
            transport=self.transport,
            code="push_unavailable",
        )
        rows = result.get("data") if isinstance(result, dict) else None
        if status != 200 or not isinstance(rows, dict):
            raise DeliveryError("push_unavailable")
        if any(
            not isinstance(row, dict) or row.get("status") not in {"ok", "error"}
            for row in rows.values()
        ):
            raise DeliveryError("push_unavailable")
        return rows


def build_messenger(settings):
    """(telegram, push) senders; None when a channel is disabled."""
    fake = FakeMessenger()
    telegram = {
        "fake": lambda: fake,
        "bot": lambda: TelegramBot(settings.telegram_bot_token_file),
    }.get(settings.telegram_bot_provider, lambda: None)()
    push = {"fake": lambda: fake, "expo": ExpoPush}.get(settings.push_provider, lambda: None)()
    return telegram, push


class Notifier:
    def __init__(self, email, telegram=None, sms=None):
        self.email, self.telegram, self.sms = email, telegram, sms

    def phone_channels(self) -> list[str]:
        return [name for name in ("telegram", "sms") if getattr(self, name) is not None]

    def send_email(self, to: str, subject: str, body: str, *, html: str | None = None) -> None:
        self.email.send(to, subject, body, html=html)

    def send_phone_code(self, channel: str, phone: str, code: str, ttl: int) -> None:
        provider = getattr(self, channel, None)
        if provider is None:
            raise DeliveryError(f"{channel}_unavailable")
        provider.send(phone, code, ttl)


def build_notifier(settings) -> Notifier:
    email = SmtpEmail(settings) if settings.email_provider == "smtp" else ConsoleEmail()
    telegram = {
        "fake": lambda: FakePhone("telegram"),
        "gateway": lambda: TelegramGateway(
            settings.telegram_gateway_token_file, proxy=settings.telegram_gateway_proxy_url
        ),
    }.get(settings.telegram_provider, lambda: None)()
    sms = FakePhone("sms") if settings.sms_provider == "fake" else None
    return Notifier(email, telegram, sms)

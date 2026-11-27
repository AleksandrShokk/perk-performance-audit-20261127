from unittest.mock import patch

import pytest

from app.integrations.email_templates import invitation_email, render_email
from app.integrations.notifications import SmtpEmail


def test_invitation_escapes_workspace_and_preserves_secret_fragment():
    text, html = invitation_email(
        '<script>alert("test")</script>',
        "Администратор",
        "owner@example.com",
        "https://perkstat.ru/invite#code=test-token&mode=join",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="https://perkstat.ru/invite#code=test-token&amp;mode=join"' in html
    assert "Принять приглашение" in html
    assert "https://perkstat.ru/invite#code=test-token&mode=join" in text
    assert "<img" not in html and "<script" not in html


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "http://evil.example/invite", "https:missing"]
)
def test_email_action_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        render_email("Test", "Body", action_url=url)


def test_smtp_sends_plain_and_html_versions(isolated_settings):
    settings = isolated_settings.model_copy(update={"smtp_security": "ssl"})
    text, html = invitation_email(
        "Тест", "Администратор", "owner@example.com", "https://perkstat.ru/invite#code=test"
    )
    with patch("app.integrations.notifications.smtplib.SMTP_SSL") as smtp:
        SmtpEmail(settings).send("owner@example.com", "Приглашение в PERK", text, html=html)
    message = smtp.return_value.send_message.call_args.args[0]
    assert message.get_content_type() == "multipart/alternative"
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == text
    assert "Принять приглашение" in message.get_body(preferencelist=("html",)).get_content()
    assert message["To"] == "owner@example.com"


def test_other_transactional_emails_get_safe_html_and_keep_original_text(isolated_settings):
    text = "Код: 123456\n\nНе сообщайте его. <script>not html</script>"
    with patch("app.integrations.notifications.smtplib.SMTP") as smtp:
        SmtpEmail(isolated_settings).send("owner@example.com", "Сброс пароля PERK", text)
    message = smtp.return_value.send_message.call_args.args[0]
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == text
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "123456" in html and "<script>" not in html

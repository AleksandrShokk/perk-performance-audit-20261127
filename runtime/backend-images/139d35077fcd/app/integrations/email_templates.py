"""Self-contained transactional emails: inline styles, no remote images or trackers."""

from html import escape
from urllib.parse import urlsplit


def render_email(
    title: str,
    body: str,
    *,
    action_label: str | None = None,
    action_url: str | None = None,
    note: str | None = None,
) -> str:
    action = ""
    if action_url:
        url = urlsplit(action_url)
        local = url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}
        if not url.hostname or (url.scheme != "https" and not local) or url.username:
            raise ValueError("Email actions require a trusted HTTPS application URL")
        safe_url = escape(action_url, quote=True)
        safe_label = escape(action_label or "Открыть PERK")
        action = f"""
        <tr><td style="padding:28px 0 0">
          <table role="presentation" cellspacing="0" cellpadding="0"><tr>
            <td bgcolor="#a79eff" style="border-radius:12px;text-align:center">
              <a href="{safe_url}" style="display:inline-block;padding:17px 28px;
                 font-size:16px;font-weight:700;color:#1c1b2a;text-decoration:none;
                 border:1px solid #a79eff;border-radius:12px">{safe_label}</a>
            </td>
          </tr></table>
        </td></tr>
        <tr><td style="padding-top:24px;font-size:12px;line-height:19px;color:#737184">
          Если кнопка не открывается, перейдите по ссылке:<br>
          <a href="{safe_url}" style="color:#625dd5;word-break:break-all">{safe_url}</a>
        </td></tr>"""
    paragraphs = "".join(
        '<p style="margin:0 0 16px;font-size:16px;line-height:26px;color:#545264">'
        + escape(part).replace("\n", "<br>")
        + "</p>"
        for part in body.split("\n\n")
    )
    footer_note = (
        f'<tr><td style="padding-top:24px;font-size:13px;line-height:21px;color:#737184">'
        f"{escape(note)}</td></tr>"
        if note
        else ""
    )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:#f4f3f8;font-family:Arial,Helvetica,sans-serif">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{escape(title)}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#f4f3f8">
<tr><td align="center" style="padding:40px 16px">
  <table role="presentation" width="560" cellspacing="0" cellpadding="0"
         style="width:100%;max-width:560px">
    <tr><td style="padding:0 0 24px 8px">
      <table role="presentation" cellspacing="0" cellpadding="0"><tr>
        <td style="padding-right:10px">
          <table role="presentation" cellspacing="3" cellpadding="0">
            <tr><td width="12" height="12" bgcolor="#625dd5" style="border-radius:4px"></td>
                <td width="12" height="12" bgcolor="#a19ee6" style="border-radius:4px"></td></tr>
            <tr><td width="12" height="12" bgcolor="#8985df" style="border-radius:4px"></td>
                <td width="12" height="12" bgcolor="#625dd5" style="border-radius:4px"></td></tr>
          </table>
        </td><td style="font-size:27px;font-weight:700;letter-spacing:1px;color:#242436">PERK</td>
      </tr></table>
    </td></tr>
    <tr><td bgcolor="#ffffff" style="padding:32px;border-radius:20px;border:1px solid #e8e6ef">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
        <tr><td><h1 style="margin:0 0 24px;font-size:26px;line-height:34px;
          font-weight:700;color:#242436">{escape(title)}</h1></td></tr>
        <tr><td>{paragraphs}</td></tr>
        {action}{footer_note}
      </table>
    </td></tr>
    <tr><td style="padding:22px 8px;font-size:12px;line-height:19px;color:#858292">
      PERK · perkstat.ru
    </td></tr>
  </table>
</td></tr></table></body></html>"""


def invitation_email(workspace: str, role: str, email: str, link: str) -> tuple[str, str]:
    text = (
        f"Вас пригласили в «{workspace}». Роль: {role}.\n\n"
        f"Принять приглашение: {link}\n\n"
        f"Войдите или зарегистрируйтесь с email {email}. "
        "Подтвердите почту и номер телефона. Ссылка одноразовая и действует 7 дней."
    )
    html = render_email(
        "Вас пригласили в команду",
        f"Вы получили приглашение в «{workspace}».\n\nВаша роль: {role}\nEmail для входа: {email}",
        action_label="Принять приглашение",
        action_url=link,
        note="Войдите или создайте аккаунт, подтвердите почту и телефон. "
        "Приглашение действует 7 дней.",
    )
    return text, html

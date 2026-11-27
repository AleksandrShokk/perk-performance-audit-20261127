"""Keep browser invitations on the trusted frontend that sent them."""

from urllib.parse import urlsplit


def invitation_link(settings, origin, code):
    base = settings.team_invite_url.rstrip("/")
    if origin and origin in settings.cors_origins:
        try:
            parsed = urlsplit(origin)
            if (
                parsed.scheme in {"http", "https"}
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and parsed.path in {"", "/"}
                and not parsed.query
                and not parsed.fragment
            ):
                base = origin.rstrip("/") + "/invite"
        except ValueError:
            pass
    # Fragments keep the one-time secret out of HTTP paths and referrers.
    return base + "#code=" + code

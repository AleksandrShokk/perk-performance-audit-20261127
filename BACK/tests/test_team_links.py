from types import SimpleNamespace

import pytest

from app.modules.accounts.team_links import invitation_link


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("http://localhost:3000", "http://localhost:3000/invite"),
        ("https://app.example.test", "https://app.example.test/invite"),
        (None, "perk://invite"),
        ("https://foreign.invalid", "perk://invite"),
        ("https://app.example.test.foreign.invalid", "perk://invite"),
        ("null", "perk://invite"),
        ("javascript:alert(1)", "perk://invite"),
    ],
)
def test_links_use_only_the_allowlisted_browser_or_native_fallback(origin, expected):
    settings = SimpleNamespace(
        team_invite_url="perk://invite",
        cors_origins=["http://localhost:3000", "https://app.example.test"],
    )
    result = invitation_link(settings, origin, "test-one-time-secret")
    assert result == expected + "#code=test-one-time-secret"
    assert "?code=" not in result


@pytest.mark.parametrize(
    "origin",
    [
        "https://app.test/path",
        "https://app.test?redirect=x",
        "https://<REDACTED>@app.test",
        "https://[",
    ],
)
def test_malformed_configured_origins_cannot_change_the_invitation_target(origin):
    settings = SimpleNamespace(
        team_invite_url="https://canonical.test/invite/", cors_origins=[origin]
    )
    assert (
        invitation_link(settings, origin, "secret") == "https://canonical.test/invite#code=secret"
    )

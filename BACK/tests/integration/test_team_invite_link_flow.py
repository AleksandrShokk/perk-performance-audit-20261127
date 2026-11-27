import pytest
from test_insights_flow import env as env
from test_insights_flow import pytestmark as pytestmark
from test_team_access import invite_code
from test_team_access import outsider as outsider


@pytest.mark.parametrize("browser", [True, False])
def test_delivered_link_opens_the_right_frontend_and_still_joins_once(env, outsider, browser):
    owner = env.login(env.owner)
    outside = env.login(outsider)
    settings = env.client.app.state.settings
    origin = settings.cors_origins[0]
    headers = {**owner, **({"Origin": origin} if browser else {})}
    result = env.client.post(
        f"/api/v1/workspaces/{env.workspace}/invites",
        json={"email": env.emails[outsider]},
        headers=headers,
    )
    assert result.status_code == 201, result.text
    code = invite_code(env, env.emails[outsider])
    body = next(body for email, body in reversed(env.inbox.emails) if email == env.emails[outsider])
    base = origin + "/invite" if browser else settings.team_invite_url.rstrip("/")
    assert base + "#code=" + code in body
    assert code not in result.text
    accepted = env.client.post("/api/v1/invites/accept", json={"code": code}, headers=outside)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["workspace_id"] == str(env.workspace)
    assert (
        env.client.post("/api/v1/invites/accept", json={"code": code}, headers=outside).status_code
        == 404
    )

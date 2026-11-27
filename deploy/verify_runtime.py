"""Private production checks: no codes sent, no user records or secrets printed."""
import json
import logging
import sys
from urllib.error import HTTPError
from urllib.request import urlopen

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import build_engine, set_actor
from app.main import create_app
from app.modules.accounts.models import Store, StoreCredential
from app.modules.auth.models import User
from app.security.crypto import SecretVault


def main():
    settings = get_settings()
    assert settings.app_env == 'production'
    assert not settings.public_registration_enabled
    assert settings.cookie_secure
    engine = build_engine(settings)
    vault = SecretVault(settings.security_file)
    checked = set()
    with Session(engine) as db:
        role = db.execute(text('SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()
        assert role[0] == 'perk_app' and not role[1] and not role[2]
        assert db.scalar(select(Store.id).limit(1)) is None, 'RLS must hide stores without an actor'
        assert db.scalar(text("SELECT perk_request_funnel_history('00000000-0000-0000-0000-000000000000'::uuid, '00000000-0000-0000-0000-000000000000'::uuid, current_date-30)")) is False
        user_ids = list(db.scalars(select(User.id)))
        for user_id in user_ids:
            set_actor(db, user_id)
            for store, credential in db.execute(select(Store, StoreCredential).join(StoreCredential, StoreCredential.store_id == Store.id)):
                if store.id in checked:
                    continue
                aad = f'wb:{store.workspace_id}:{store.id}' if store.marketplace == 'wildberries' else f'ozon-seller:v1:{store.workspace_id}:{store.id}'
                value = vault.open(credential.ciphertext, aad)
                assert value
                if store.marketplace == 'ozon':
                    data = json.loads(value)
                    assert data['client_id'] == store.external_seller_id and data['api_key']
                checked.add(store.id)
            for user in db.scalars(select(User).where(User.id == user_id)):
                if user.totp_ciphertext:
                    assert vault.open(user.totp_ciphertext, f'totp:{user.id}')
        db.rollback()
    engine.dispose()
    for path in ('live', 'ready'):
        with urlopen(f'http://127.0.0.1:8000/api/v1/health/{path}', timeout=15) as response:
            assert response.status == 200 and json.load(response)['status'] == 'ok'
    try:
        urlopen('http://127.0.0.1:8000/api/v1/auth/me', timeout=15)
    except HTTPError as error:
        assert error.code == 400 and json.load(error)['message'] == 'HTTPS required'
    else:
        raise AssertionError('Unencrypted auth must be rejected')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    with TestClient(create_app(settings), base_url='https://perkstat.ru') as client:
        assert client.get('/api/v1/auth/me').status_code == 401
        response = client.post('/api/v1/auth/register', json={
            'email': 'deployment-check@example.com', 'password': 'Private deployment check 2026',
            'workspace_name': 'Deployment check', 'client': 'mobile'})
        assert response.status_code == 403 and response.json()['code'] == 'registration_closed'
        assert client.get('/docs').status_code == 404
        assert client.get('/openapi.json').status_code == 404
    print(json.dumps({'production_config': True, 'restricted_runtime_role': True,
        'rls_hides_other_workspaces': True, 'credentials_decrypted': len(checked),
        'users_checked': len(user_ids), 'health': 'ok', 'https_required': True,
        'unauthenticated_access_rejected': True, 'public_registration_closed': True,
        'docs_hidden': True}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'runtime_verification': False, 'error_type': type(error).__name__}))
        sys.exit(1)

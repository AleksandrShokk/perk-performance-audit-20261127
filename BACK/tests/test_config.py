from app.core.config import Settings


def test_database_password_with_special_characters_is_preserved_and_redacted():
    secret = "demo@password:/#%"
    settings = Settings(_env_file=None, postgres_password=secret)
    assert settings.database_url.password == secret
    assert secret not in str(settings.database_url)
    assert secret not in repr(settings)

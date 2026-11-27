"""Run only in the migration/admin container; runtime never receives admin credentials."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from psycopg import connect, sql


def main():
    settings = get_settings()
    command.upgrade(Config("alembic.ini"), "head")
    password = (
        Path(os.environ.get("APP_DB_PASSWORD_FILE", ".secrets/db-app-password")).read_text().strip()
    )
    url = settings.database_url
    with connect(
        host=url.host, port=url.port, user=url.username, password=url.password, dbname=url.database
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'perk_app'")
            if not cursor.fetchone():
                cursor.execute(
                    "CREATE ROLE perk_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOINHERIT NOBYPASSRLS"
                )
            cursor.execute(sql.SQL("ALTER ROLE perk_app PASSWORD {}").format(sql.Literal(password)))
            cursor.execute(
                "ALTER ROLE perk_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            )
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute("GRANT USAGE ON SCHEMA public TO perk_app")
            cursor.execute("GRANT EXECUTE ON FUNCTION perk_notification_users() TO perk_app")
            cursor.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO perk_app"
            )
            cursor.execute("REVOKE ALL ON alembic_version FROM perk_app")
            cursor.execute("REVOKE UPDATE, DELETE ON audit_events FROM perk_app")
            # Team management changes roles and removes members; forced RLS limits it to
            # workspace owners (and a member leaving on their own).
            cursor.execute("GRANT UPDATE, DELETE ON memberships TO perk_app")
            # Ownership transfer is not implemented: nobody can silently replace the creator.
            cursor.execute("REVOKE UPDATE ON workspaces FROM perk_app")
            cursor.execute("GRANT UPDATE (name, timezone, currency) ON workspaces TO perk_app")
            cursor.execute("REVOKE UPDATE ON memberships FROM perk_app")
            cursor.execute("GRANT UPDATE (role, permissions, store_ids) ON memberships TO perk_app")
            cursor.execute("GRANT EXECUTE ON FUNCTION perk_accept_invite(text) TO perk_app")
            cursor.execute("GRANT EXECUTE ON FUNCTION perk_invite_details(text) TO perk_app")
            cursor.execute("GRANT EXECUTE ON FUNCTION perk_lock_store(uuid,uuid,text) TO perk_app")
            cursor.execute(
                "REVOKE DELETE ON users, auth_sessions, access_tokens, refresh_tokens FROM perk_app"
            )
            cursor.execute(
                "GRANT EXECUTE ON FUNCTION perk_queue_actors(text), perk_sync_actor(uuid,text), "
                "perk_ozon_request_history(uuid,uuid,text,date,date,boolean) TO perk_app"
            )
            cursor.execute(
                "GRANT EXECUTE ON FUNCTION "
                "perk_reject_ozon_job(uuid,uuid,text,uuid,uuid) TO perk_app"
            )
            # Expired rows only: the function body is fixed and owned by the migration role.
            cursor.execute("GRANT EXECUTE ON FUNCTION perk_cleanup_expired(integer) TO perk_app")
    print("Migrations applied; restricted runtime role configured.")


if __name__ == "__main__":
    main()

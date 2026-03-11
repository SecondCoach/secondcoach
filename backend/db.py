import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./secondcoach.db")


def _is_postgres(url: str) -> bool:
    return url.startswith("postgres://") or url.startswith("postgresql://")


def _normalize_postgres_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def _sqlite_path_from_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "", 1)
    return "secondcoach.db"


@contextmanager
def get_conn():
    if _is_postgres(DATABASE_URL):
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL apunta a Postgres pero psycopg2 no está instalado."
            ) from exc

        conn = psycopg2.connect(
            _normalize_postgres_url(DATABASE_URL),
            cursor_factory=RealDictCursor,
        )
        try:
            yield conn
        finally:
            conn.close()
    else:
        db_path = _sqlite_path_from_url(DATABASE_URL)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def init_db() -> None:
    with get_conn() as conn:
        cur = conn.cursor()

        if _is_postgres(DATABASE_URL):
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    strava_athlete_id BIGINT UNIQUE NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    expires_at BIGINT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_users_strava_athlete_id
                ON users (strava_athlete_id);
                """
            )

            conn.commit()
            return

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strava_athlete_id INTEGER UNIQUE NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_strava_athlete_id
            ON users (strava_athlete_id);
            """
        )
        conn.commit()


def _row_to_dict(row: Any) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def get_user_by_athlete_id(strava_athlete_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()

        if _is_postgres(DATABASE_URL):
            cur.execute(
                """
                SELECT id, strava_athlete_id, access_token, refresh_token, expires_at,
                       created_at, updated_at
                FROM users
                WHERE strava_athlete_id = %s
                LIMIT 1
                """,
                (strava_athlete_id,),
            )
        else:
            cur.execute(
                """
                SELECT id, strava_athlete_id, access_token, refresh_token, expires_at,
                       created_at, updated_at
                FROM users
                WHERE strava_athlete_id = ?
                LIMIT 1
                """,
                (strava_athlete_id,),
            )

        return _row_to_dict(cur.fetchone())


def upsert_user(
    strava_athlete_id: int,
    access_token: str,
    refresh_token: str,
    expires_at: int,
    username: Optional[str] = None,
    firstname: Optional[str] = None,
    lastname: Optional[str] = None,
) -> None:
    # username, firstname y lastname se aceptan para mantener compatibilidad
    # con main.py aunque en este MVP todavía no se persisten en la tabla.
    _ = (username, firstname, lastname)

    now_iso = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        cur = conn.cursor()

        if _is_postgres(DATABASE_URL):
            cur.execute(
                """
                INSERT INTO users (
                    strava_athlete_id, access_token, refresh_token, expires_at, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (strava_athlete_id)
                DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = NOW()
                """,
                (strava_athlete_id, access_token, refresh_token, expires_at),
            )
            conn.commit()
            return

        cur.execute(
            """
            INSERT INTO users (
                strava_athlete_id, access_token, refresh_token, expires_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(strava_athlete_id)
            DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (
                strava_athlete_id,
                access_token,
                refresh_token,
                expires_at,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()
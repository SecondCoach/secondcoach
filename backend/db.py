import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "secondcoach.db"))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strava_athlete_id INTEGER NOT NULL UNIQUE,
                access_token TEXT,
                refresh_token TEXT,
                expires_at INTEGER,
                username TEXT,
                firstname TEXT,
                lastname TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS users_updated_at_trigger
            AFTER UPDATE ON users
            FOR EACH ROW
            BEGIN
                UPDATE users
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = OLD.id;
            END;
            """
        )
        conn.commit()


def upsert_user(
    strava_athlete_id: int,
    access_token: str,
    refresh_token: str,
    expires_at: int,
    username: Optional[str] = None,
    firstname: Optional[str] = None,
    lastname: Optional[str] = None,
) -> None:
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (
                strava_athlete_id,
                access_token,
                refresh_token,
                expires_at,
                username,
                firstname,
                lastname
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(strava_athlete_id) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                username = excluded.username,
                firstname = excluded.firstname,
                lastname = excluded.lastname
            """,
            (
                strava_athlete_id,
                access_token,
                refresh_token,
                expires_at,
                username,
                firstname,
                lastname,
            ),
        )
        conn.commit()


def get_user_by_athlete_id(strava_athlete_id: int) -> Optional[Dict[str, Any]]:
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                strava_athlete_id,
                access_token,
                refresh_token,
                expires_at,
                username,
                firstname,
                lastname
            FROM users
            WHERE strava_athlete_id = ?
            """,
            (strava_athlete_id,),
        ).fetchone()

    return dict(row) if row else None
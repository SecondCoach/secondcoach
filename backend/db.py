import sqlite3
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "backend" / "users.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_user_table() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strava_athlete_id INTEGER NOT NULL UNIQUE,
                access_token TEXT,
                refresh_token TEXT,
                expires_at INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def save_user(
    strava_athlete_id: int,
    access_token: str,
    refresh_token: Optional[str],
    expires_at: Optional[int],
) -> None:
    ensure_user_table()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (
                strava_athlete_id, access_token, refresh_token, expires_at, updated_at
            )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(strava_athlete_id)
            DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (strava_athlete_id, access_token, refresh_token, expires_at),
        )
        conn.commit()


def get_user_by_athlete_id(strava_athlete_id: int) -> Optional[dict]:
    ensure_user_table()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT strava_athlete_id, access_token, refresh_token, expires_at, updated_at
            FROM users
            WHERE strava_athlete_id = ?
            """,
            (strava_athlete_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "strava_athlete_id": row["strava_athlete_id"],
        "access_token": row["access_token"],
        "refresh_token": row["refresh_token"],
        "expires_at": row["expires_at"],
        "updated_at": row["updated_at"],
    }
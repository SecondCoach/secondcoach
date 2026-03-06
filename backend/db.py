import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path("secondcoach.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    return dict(row)


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strava_athlete_id INTEGER UNIQUE NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def upsert_user(
    strava_athlete_id: int,
    access_token: str,
    refresh_token: str,
    expires_at: int,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (
                strava_athlete_id,
                access_token,
                refresh_token,
                expires_at,
                updated_at
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
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                strava_athlete_id,
                access_token,
                refresh_token,
                expires_at,
                created_at,
                updated_at
            FROM users
            WHERE strava_athlete_id = ?
            LIMIT 1
            """,
            (strava_athlete_id,),
        ).fetchone()
        return row_to_dict(row)


def get_user_count() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"])


init_db()
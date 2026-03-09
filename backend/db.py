import os
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no configurado")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            strava_athlete_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            firstname TEXT,
            lastname TEXT,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            expires_at BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS firstname TEXT;")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS lastname TEXT;")

    conn.commit()
    cur.close()
    conn.close()


def upsert_user(
    strava_athlete_id: int,
    access_token: str,
    refresh_token: str,
    expires_at: int,
    username: Optional[str] = None,
    firstname: Optional[str] = None,
    lastname: Optional[str] = None,
):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO users (
            strava_athlete_id,
            username,
            firstname,
            lastname,
            access_token,
            refresh_token,
            expires_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (strava_athlete_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            firstname = EXCLUDED.firstname,
            lastname = EXCLUDED.lastname,
            access_token = EXCLUDED.access_token,
            refresh_token = EXCLUDED.refresh_token,
            expires_at = EXCLUDED.expires_at,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            strava_athlete_id,
            username,
            firstname,
            lastname,
            access_token,
            refresh_token,
            expires_at,
        ),
    )

    conn.commit()
    cur.close()
    conn.close()


def get_user_by_athlete_id(athlete_id: int) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM users
        WHERE strava_athlete_id = %s
        LIMIT 1
        """,
        (athlete_id,),
    )

    row = cur.fetchone()

    cur.close()
    conn.close()

    return row


def get_user_count() -> int:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS count FROM users")
    row = cur.fetchone()

    cur.close()
    conn.close()

    return int(row["count"])


def list_user_athlete_ids() -> list[int]:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT strava_athlete_id
        FROM users
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [int(row["strava_athlete_id"]) for row in rows]
import sqlite3
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "backend" / "users.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_goal_table() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strava_athlete_id INTEGER NOT NULL UNIQUE,
                race_type TEXT,
                race_name TEXT,
                race_date TEXT,
                goal_time TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def save_user_goal(
    strava_athlete_id: int,
    race_type: str,
    race_name: str,
    race_date: str,
    goal_time: str,
) -> None:
    ensure_goal_table()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_goals (
                strava_athlete_id, race_type, race_name, race_date, goal_time, updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(strava_athlete_id)
            DO UPDATE SET
                race_type = excluded.race_type,
                race_name = excluded.race_name,
                race_date = excluded.race_date,
                goal_time = excluded.goal_time,
                updated_at = CURRENT_TIMESTAMP
            """,
            (strava_athlete_id, race_type, race_name, race_date, goal_time),
        )
        conn.commit()


def get_user_goal(strava_athlete_id: int) -> Optional[dict]:
    ensure_goal_table()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT strava_athlete_id, race_type, race_name, race_date, goal_time, updated_at
            FROM user_goals
            WHERE strava_athlete_id = ?
            """,
            (strava_athlete_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "strava_athlete_id": row["strava_athlete_id"],
        "race_type": row["race_type"],
        "race_name": row["race_name"],
        "race_date": row["race_date"],
        "goal_time": row["goal_time"],
        "updated_at": row["updated_at"],
    }
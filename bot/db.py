import logging
import sqlite3

from bot.config import settings

logger = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(settings.db_path)


def init() -> None:
    """Create tables if they don't exist. Call once at startup."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                user_id INTEGER NOT NULL,
                key     TEXT    NOT NULL,
                value   TEXT    NOT NULL,
                PRIMARY KEY (user_id, key)
            )
        """)
    logger.info("Database initialised (db=%s)", settings.db_path)


def get_facts(user_id: int) -> dict[str, str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT key, value FROM facts WHERE user_id = ? ORDER BY key",
            (user_id,),
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def set_fact(user_id: int, key: str, value: str) -> None:
    logger.debug("set_fact: user=%d key=%r value=%r", user_id, key, value)
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO facts (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, key, value),
        )


def remove_fact(user_id: int, key: str) -> bool:
    logger.debug("remove_fact: user=%d key=%r", user_id, key)
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM facts WHERE user_id = ? AND key = ?",
            (user_id, key),
        )
    return cursor.rowcount > 0

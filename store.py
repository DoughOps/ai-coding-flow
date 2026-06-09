import sqlite3
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def init_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                platform     TEXT NOT NULL,
                repo_url     TEXT NOT NULL DEFAULT '',
                issue_number INTEGER NOT NULL,
                issue_title  TEXT NOT NULL,
                engine       TEXT NOT NULL DEFAULT '',
                status       TEXT NOT NULL DEFAULT 'queued',
                pr_url       TEXT NOT NULL DEFAULT '',
                error_msg    TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        """)
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN repo_url TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass


def create_job(
    db_path: str,
    *,
    platform: str,
    issue_number: int,
    issue_title: str,
    repo_url: str = "",
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO jobs (platform, repo_url, issue_number, issue_title, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (platform, repo_url, issue_number, issue_title, now, now),
        )
        return cur.lastrowid


def update_job(db_path: str, job_id: int, **fields) -> None:
    allowed = {"status", "engine", "pr_url", "error_msg"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    now = datetime.now(timezone.utc).isoformat()
    updates["updated_at"] = now
    cols = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [job_id]
    with sqlite3.connect(db_path) as conn:
        result = conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", values)
        if result.rowcount == 0:
            logger.warning("update_job: no row with id=%d", job_id)


def list_jobs(db_path: str, limit: int = 50, offset: int = 0) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    return [dict(row) for row in rows]

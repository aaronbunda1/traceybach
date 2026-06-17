"""Persistence layer for the Bach Bash planner.

Dual-mode by design:
  * Local dev / tests  -> a single local SQLite file (zero setup).
  * Hosted             -> Postgres, when a DATABASE_URL env var is set (e.g.
                          a free Neon database on Streamlit Community Cloud).

The host filesystem on free platforms is ephemeral, so SQLite-on-disk would be
wiped on every reboot. Pointing DATABASE_URL at a managed Postgres keeps the
crew's votes/expenses/etc. durable across restarts. The SQL we use is almost
identical across both engines; the few differences (autoincrement, placeholder
style, last-insert-id, schema execution) are handled in `_Conn` below.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Iterable, Optional

DB_PATH = os.environ.get("BACH_DB_PATH", os.path.join(os.path.dirname(__file__), "bach_bash.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS participants (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    email      TEXT,
    created_at TEXT NOT NULL
);

-- One row per (participant, date). status in ('yes','maybe','no').
CREATE TABLE IF NOT EXISTS availability (
    participant_id INTEGER NOT NULL,
    day            TEXT NOT NULL,
    status         TEXT NOT NULL,
    PRIMARY KEY (participant_id, day),
    FOREIGN KEY (participant_id) REFERENCES participants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS budget_items (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    planned  REAL NOT NULL DEFAULT 0,
    notes    TEXT
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    amount      REAL NOT NULL,
    paid_by     INTEGER NOT NULL,
    spent_on    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (paid_by) REFERENCES participants(id) ON DELETE CASCADE
);

-- Who an expense is split across. share is the dollar amount owed by that
-- participant for that expense (lets us support uneven splits later).
CREATE TABLE IF NOT EXISTS expense_shares (
    expense_id     INTEGER NOT NULL,
    participant_id INTEGER NOT NULL,
    share          REAL NOT NULL,
    PRIMARY KEY (expense_id, participant_id),
    FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE,
    FOREIGN KEY (participant_id) REFERENCES participants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ideas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    url        TEXT,
    notes      TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idea_votes (
    idea_id        INTEGER NOT NULL,
    participant_id INTEGER NOT NULL,
    PRIMARY KEY (idea_id, participant_id),
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE,
    FOREIGN KEY (participant_id) REFERENCES participants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS checklist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    label      TEXT NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    owner_id   INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES participants(id) ON DELETE SET NULL
);

-- One vote per participant for the destination city. city is a short key
-- (e.g. 'puerto_rico'); each participant votes for at most one city.
CREATE TABLE IF NOT EXISTS city_votes (
    participant_id INTEGER PRIMARY KEY,
    city           TEXT NOT NULL,
    FOREIGN KEY (participant_id) REFERENCES participants(id) ON DELETE CASCADE
);
"""


# ----------------------------------------------------------- engine select ---
def _database_url() -> str:
    """Normalized Postgres URL, or '' when running on local SQLite."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):  # SQLAlchemy/Heroku-style alias
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _is_postgres() -> bool:
    return _database_url().startswith("postgresql://")


class _Conn:
    """Thin wrapper so the same query code runs on SQLite and Postgres.

    Translates the `?` placeholder style to `%s` for Postgres and papers over
    the last-insert-id difference (`cursor.lastrowid` vs `RETURNING id`).
    """

    def __init__(self, raw, backend: str):
        self.raw = raw
        self.backend = backend

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.backend == "postgres" else sql

    def execute(self, sql: str, params: Iterable = ()):
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(params))
        return cur

    def executemany(self, sql: str, seq):
        cur = self.raw.cursor()
        cur.executemany(self._sql(sql), [tuple(p) for p in seq])
        return cur

    def insert_id(self, sql: str, params: Iterable = ()):
        """Run an INSERT and return the new row's integer id."""
        if self.backend == "postgres":
            cur = self.execute(sql + " RETURNING id", params)
            return cur.fetchone()["id"]
        cur = self.execute(sql, params)
        return cur.lastrowid


@contextmanager
def get_conn():
    if _is_postgres():
        import psycopg
        from psycopg.rows import dict_row

        raw = psycopg.connect(_database_url(), row_factory=dict_row)
        conn = _Conn(raw, "postgres")
    else:
        raw = sqlite3.connect(DB_PATH)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        conn = _Conn(raw, "sqlite")
    try:
        yield conn
        raw.commit()
    finally:
        raw.close()


def init_db() -> None:
    with get_conn() as conn:
        if conn.backend == "postgres":
            pg_schema = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            # Strip `-- ...` line comments first: a comment may contain a ';',
            # which would otherwise break the naive split-on-statement below.
            pg_schema = re.sub(r"--[^\n]*", "", pg_schema)
            for stmt in pg_schema.split(";"):
                if "CREATE TABLE" in stmt.upper():
                    conn.execute(stmt)
        else:
            conn.raw.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- settings ---
def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


# ------------------------------------------------------------ participants ---
def add_participant(name: str, email: str = "") -> int:
    name = name.strip()
    if not name:
        raise ValueError("name required")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO participants(name, email, created_at) VALUES(?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET email = excluded.email",
            (name, email.strip(), _now()),
        )
        row = conn.execute("SELECT id FROM participants WHERE name = ?", (name,)).fetchone()
    return row["id"]


def list_participants() -> list[dict]:
    # Return plain dicts: these are used as Streamlit widget options, and
    # Streamlit must pickle the selected option into session state.
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM participants ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def remove_participant(pid: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM participants WHERE id = ?", (pid,))


# ------------------------------------------------------------ availability ---
def set_availability(participant_id: int, day: date, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO availability(participant_id, day, status) VALUES(?, ?, ?) "
            "ON CONFLICT(participant_id, day) DO UPDATE SET status = excluded.status",
            (participant_id, day.isoformat(), status),
        )


def get_availability() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM availability").fetchall()]


# ------------------------------------------------------------------ budget ---
def add_budget_item(category: str, planned: float, notes: str = "") -> int:
    with get_conn() as conn:
        return conn.insert_id(
            "INSERT INTO budget_items(category, planned, notes) VALUES(?, ?, ?)",
            (category.strip(), float(planned), notes.strip()),
        )


def list_budget_items() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM budget_items ORDER BY category").fetchall()]


def remove_budget_item(item_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM budget_items WHERE id = ?", (item_id,))


# ---------------------------------------------------------------- expenses ---
def add_expense(
    description: str,
    amount: float,
    paid_by: int,
    split_among: Iterable[int],
    spent_on: Optional[date] = None,
) -> int:
    split_among = list(split_among)
    if not split_among:
        raise ValueError("split_among must contain at least one participant")
    amount = float(amount)
    spent_on = spent_on or date.today()
    # Even split, with the rounding remainder pushed onto the payer so shares
    # always sum exactly to the total.
    n = len(split_among)
    base = round(amount / n, 2)
    shares = {pid: base for pid in split_among}
    remainder = round(amount - base * n, 2)
    first = split_among[0]
    shares[first] = round(shares[first] + remainder, 2)
    with get_conn() as conn:
        eid = conn.insert_id(
            "INSERT INTO expenses(description, amount, paid_by, spent_on, created_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (description.strip(), amount, paid_by, spent_on.isoformat(), _now()),
        )
        conn.executemany(
            "INSERT INTO expense_shares(expense_id, participant_id, share) VALUES(?, ?, ?)",
            [(eid, pid, shares[pid]) for pid in split_among],
        )
    return eid


def list_expenses() -> list[dict]:
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT e.*, p.name AS payer_name FROM expenses e "
                "JOIN participants p ON p.id = e.paid_by ORDER BY e.spent_on DESC, e.id DESC"
            ).fetchall()
        ]


def get_expense_shares() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM expense_shares").fetchall()]


def remove_expense(expense_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))


# ------------------------------------------------------------------- ideas ---
def add_idea(title: str, url: str = "", notes: str = "") -> int:
    with get_conn() as conn:
        return conn.insert_id(
            "INSERT INTO ideas(title, url, notes, created_at) VALUES(?, ?, ?, ?)",
            (title.strip(), url.strip(), notes.strip(), _now()),
        )


def list_ideas() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM ideas ORDER BY created_at DESC").fetchall()]


def remove_idea(idea_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))


def toggle_vote(idea_id: int, participant_id: int) -> None:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM idea_votes WHERE idea_id = ? AND participant_id = ?",
            (idea_id, participant_id),
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM idea_votes WHERE idea_id = ? AND participant_id = ?",
                (idea_id, participant_id),
            )
        else:
            conn.execute(
                "INSERT INTO idea_votes(idea_id, participant_id) VALUES(?, ?)",
                (idea_id, participant_id),
            )


def vote_counts() -> dict[int, int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT idea_id, COUNT(*) AS n FROM idea_votes GROUP BY idea_id"
        ).fetchall()
    return {r["idea_id"]: r["n"] for r in rows}


# -------------------------------------------------------------- city votes ---
def set_city_vote(participant_id: int, city: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO city_votes(participant_id, city) VALUES(?, ?) "
            "ON CONFLICT(participant_id) DO UPDATE SET city = excluded.city",
            (participant_id, city),
        )


def clear_city_vote(participant_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM city_votes WHERE participant_id = ?", (participant_id,))


def get_city_votes() -> dict[int, str]:
    """participant_id -> city key."""
    with get_conn() as conn:
        rows = conn.execute("SELECT participant_id, city FROM city_votes").fetchall()
    return {r["participant_id"]: r["city"] for r in rows}


def city_vote_counts() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT city, COUNT(*) AS n FROM city_votes GROUP BY city"
        ).fetchall()
    return {r["city"]: r["n"] for r in rows}


# --------------------------------------------------------------- checklist ---
def add_checklist_item(label: str, owner_id: Optional[int] = None) -> int:
    with get_conn() as conn:
        return conn.insert_id(
            "INSERT INTO checklist(label, owner_id, created_at) VALUES(?, ?, ?)",
            (label.strip(), owner_id, _now()),
        )


def list_checklist() -> list[dict]:
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT c.*, p.name AS owner_name FROM checklist c "
                "LEFT JOIN participants p ON p.id = c.owner_id ORDER BY c.done, c.id"
            ).fetchall()
        ]


def set_checklist_done(item_id: int, done: bool) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE checklist SET done = ? WHERE id = ?", (1 if done else 0, item_id))


def remove_checklist_item(item_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM checklist WHERE id = ?", (item_id,))

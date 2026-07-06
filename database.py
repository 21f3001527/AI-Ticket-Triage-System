
import sqlite3

DB_FILE = "tickets.db"


def init_db():
    """Create the tickets table if it doesn't already exist."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_text TEXT,
            category TEXT,
            priority TEXT,
            sentiment TEXT,
            suggested_reply TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_results(results):
    """Write a list of analyzed tickets into the database."""
    conn = sqlite3.connect(DB_FILE)
    for r in results:
        conn.execute(
            """INSERT INTO tickets (ticket_text, category, priority, sentiment, suggested_reply)
               VALUES (?, ?, ?, ?, ?)""",
            (r["ticket_text"], r["category"], r["priority"], r["sentiment"], r["suggested_reply"]),
        )
    conn.commit()
    conn.close()


def load_history(priority_filter=None):
    """
    Read saved tickets, newest first.
    If priority_filter is given (e.g. "urgent"), only return those.
    """
    conn = sqlite3.connect(DB_FILE)
    if priority_filter and priority_filter != "all":
        rows = conn.execute(
            """SELECT ticket_text, category, priority, sentiment, suggested_reply, created_at
               FROM tickets WHERE priority = ? ORDER BY id DESC""",
            (priority_filter,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT ticket_text, category, priority, sentiment, suggested_reply, created_at
               FROM tickets ORDER BY id DESC"""
        ).fetchall()
    conn.close()
    return rows

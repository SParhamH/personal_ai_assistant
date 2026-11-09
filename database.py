"""
database.py - Al's SQLite database for chats.
Prototype: The file, two tables, and test
"""

import sqlite3
from datetime import datetime
from pathlib import Path

# Lives in memory/
DB_FILE = Path(__file__).parent / "memory" / "al.db"


def connect():
    """Opens the database file. SQLite creates it if it doesn't exist yet."""
    DB_FILE.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_FILE)


def setup():
    """Makes the two tables if they are missing. Safe to run every time Al starts."""
    conn = connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started TEXT NOT NULL)
        """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        reply_type TEXT NOT NULL DEFAULT 'normal',
        mode TEXT NOT NULL DEFAULT 'casual',
        verified INTEGER,
        content TEXT NOT NULL,
        time TEXT NOT NULL)
        """)
    conn.commit()
    conn.close()


def start_session(started):
    """Adds a new chat and returns its number."""
    conn = connect()
    cursor = conn.execute(
        "INSERT INTO sessions (started) VALUES (?)", (started,))
    conn.commit()
    session_id = cursor.lastrowid
    conn.close()
    return session_id


def add_message(session_id, role, content, time, reply_type="normal", mode="casual", verified=None):
    """
    Saves one message.
    role: 'user' or 'assistant'. 
    reply_type: 'normal' or 'expanded'. 
    mode: 'casual' or 'task'.
    verified: True (me), False (guest), or None (unknown, for old imported chats).
    """
    # SQLite has no True/False, so True -> 1, False -> 0
    if verified is not None:
        verified = int(verified)
    conn = connect()
    conn.execute(
        "INSERT INTO messages (session_id, role, reply_type, mode, verified, content, time) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, role, reply_type, mode, verified, content, time),
    )
    conn.commit()
    conn.close()


def first_user_message():
    """The oldest thing the user ever said, as (content, time). None if nothing is saved yet."""
    conn = connect()
    row = conn.execute(
        "SELECT content, time FROM messages WHERE role = 'user' ORDER BY id LIMIT 1").fetchone()
    conn.close()
    return row


def session_messages(session_id):
    """Every message in one chat, in order, as (role, content) pairs."""
    conn = connect()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id", (session_id,),).fetchall()
    conn.close()
    return rows


# TEST
if __name__ == "__main__":
    # Test on a throwaway file, so the real al.db is never touched
    DB_FILE = DB_FILE.with_name("test.db")
    DB_FILE.unlink(missing_ok=True)

    # Step 1: tables
    setup()
    setup()  # a second run should change nothing
    conn = connect()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    print(tables)
    print([col[1] for col in conn.execute("PRAGMA table_info(messages)")])
    conn.close()

    # Step 2: a chat and some messages
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sid = start_session(now)
    print(sid)  # expect 1
    add_message(sid, "user", "hello Al", now, verified=True)
    add_message(sid, "assistant", "Good day, sir.", now, verified=True)
    add_message(sid, "assistant", "According to PRIMETIMER...", now,
                reply_type="expanded", mode="task", verified=True)
    add_message(sid, "user", "an old imported message",
                now)  # verified left empty

    conn = connect()
    for row in conn.execute("SELECT id, role, reply_type, mode, verified FROM messages"):
        print(row)
    conn.close()

    # Step 3: reading back
    print(first_user_message())   # expect ('hello Al', '<the time>')
    print(session_messages(sid))

    # Clean up: always the very last line
    DB_FILE.unlink()

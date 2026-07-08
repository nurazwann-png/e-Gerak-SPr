"""SQLite data layer for the e-Gerak SPR Streamlit app.

Reads and writes the SAME database file used by the existing Node.js
backend (server/server.js / server/movements.db), so records created by
either system are visible to both. Schema matches server/server.js exactly.
"""

import os
import random
import sqlite3
import string
import time

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "server", "movements.db"),
)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS movements (
            id TEXT PRIMARY KEY,
            nama TEXT NOT NULL,
            tarikh TEXT NOT NULL,
            destinasi TEXT NOT NULL,
            tujuan TEXT NOT NULL,
            nota TEXT,
            submittedBy TEXT NOT NULL
        )
        """
    )
    return conn


def generate_id():
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=7))
    return f"rec_{int(time.time() * 1000):x}_{rand}"


def list_movements():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM movements ORDER BY tarikh DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def insert_movement(nama, tarikh, destinasi, tujuan, nota, submitted_by):
    record_id = generate_id()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO movements (id, nama, tarikh, destinasi, tujuan, nota, submittedBy)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (record_id, nama, tarikh, destinasi, tujuan, nota or "", submitted_by),
        )
        conn.commit()
        return record_id
    finally:
        conn.close()


def delete_movement(record_id, requester_email):
    """Deletes a record only if requester_email matches the original submitter."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT submittedBy FROM movements WHERE id = ?", (record_id,)
        ).fetchone()
        if row is None:
            return False, "Rekod tidak dijumpai."
        if row["submittedBy"] != requester_email:
            return False, "Anda hanya boleh memadam rekod yang anda hantar sendiri."
        conn.execute("DELETE FROM movements WHERE id = ?", (record_id,))
        conn.commit()
        return True, None
    finally:
        conn.close()


def delete_all():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM movements")
        conn.commit()
    finally:
        conn.close()

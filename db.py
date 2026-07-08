"""SQLite data layer for the e-Gerak SPR Streamlit app.

Prefers the SAME database file used by the existing Node.js backend
(server/server.js / server/movements.db), so records created by either
system are visible to both. Schema matches server/server.js exactly.

Some hosts (e.g. Streamlit Community Cloud) mount the app source
read-only, so that path can't be created/written there. In that case we
fall back to a writable temp-directory database - see _resolve_db_path().
"""

import os
import random
import sqlite3
import string
import tempfile
import time

PREFERRED_DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(__file__), "server", "movements.db"),
)
FALLBACK_DB_PATH = os.path.join(tempfile.gettempdir(), "e_gerak_spr_movements.db")

_resolved_db_path = None
_using_fallback = False

SCHEMA = """
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


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def _resolve_db_path():
    """Picks PREFERRED_DB_PATH if writable, otherwise a temp-dir fallback.

    Cached for the life of the process so we don't retry a known-broken
    path (and its OperationalError) on every rerun.
    """
    global _resolved_db_path, _using_fallback
    if _resolved_db_path is not None:
        return _resolved_db_path
    try:
        os.makedirs(os.path.dirname(PREFERRED_DB_PATH), exist_ok=True)
        _connect(PREFERRED_DB_PATH).close()
        _resolved_db_path = PREFERRED_DB_PATH
    except (sqlite3.OperationalError, OSError):
        _resolved_db_path = FALLBACK_DB_PATH
        _using_fallback = True
    return _resolved_db_path


def is_using_fallback_storage():
    _resolve_db_path()
    return _using_fallback


def get_connection():
    return _connect(_resolve_db_path())


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

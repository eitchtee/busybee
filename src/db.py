import sqlite3
import os


DB_FILE = os.path.join("data", "sync_state.db")


def get_connection():
    return sqlite3.connect(DB_FILE)


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_tokens (
                account_id TEXT PRIMARY KEY,
                sync_token TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS event_map (
                source_event_id TEXT,
                source_account TEXT,
                target_event_id TEXT,
                target_account TEXT,
                end_date TEXT,
                PRIMARY KEY (source_event_id, target_account)
            )
        """)

        # Check if we need to migrate an old schema
        cursor.execute("PRAGMA table_info(event_map)")
        columns = [info[1] for info in cursor.fetchall()]
        if "end_date" not in columns:
            cursor.execute("ALTER TABLE event_map ADD COLUMN end_date TEXT")

        conn.commit()


def get_sync_token(account_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sync_token FROM sync_tokens WHERE account_id = ?", (account_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None


def set_sync_token(account_id, sync_token):
    with get_connection() as conn:
        cursor = conn.cursor()
        if sync_token is None:
            cursor.execute(
                "DELETE FROM sync_tokens WHERE account_id = ?", (account_id,)
            )
        else:
            cursor.execute(
                """
                INSERT INTO sync_tokens (account_id, sync_token) 
                VALUES (?, ?) 
                ON CONFLICT(account_id) DO UPDATE SET sync_token=excluded.sync_token
            """,
                (account_id, sync_token),
            )
        conn.commit()


def record_mapping(
    source_event_id, source_account, target_event_id, target_account, end_date
):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO event_map (source_event_id, source_account, target_event_id, target_account, end_date)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_event_id, target_account) DO UPDATE SET end_date=excluded.end_date
        """,
            (
                source_event_id,
                source_account,
                target_event_id,
                target_account,
                end_date,
            ),
        )
        conn.commit()


def get_mapped_event(source_event_id, target_account):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT target_event_id FROM event_map 
            WHERE source_event_id = ? AND target_account = ?
        """,
            (source_event_id, target_account),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def delete_mapping(source_event_id, target_account):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM event_map
            WHERE source_event_id = ? AND target_account = ?
        """,
            (source_event_id, target_account),
        )
        conn.commit()


def get_all_mapped_events():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT target_event_id, target_account FROM event_map")
        return cursor.fetchall()


def get_all_mappings():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT source_event_id, target_account, end_date FROM event_map"
        )
        return cursor.fetchall()


def clear_all_data():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM event_map")
        cursor.execute("DELETE FROM sync_tokens")
        conn.commit()

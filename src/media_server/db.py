import os
import sqlite3
import threading
import time


class MediaDB:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self):
        return sqlite3.connect(self.path, check_same_thread=False)

    def _init_schema(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS media_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    tiny_fingerprint TEXT,
                    object_key TEXT NOT NULL,
                    file_name TEXT,
                    file_path TEXT,
                    created_at INTEGER NOT NULL,
                    UNIQUE(workspace_id, fingerprint)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_tiny ON media_files(workspace_id, tiny_fingerprint)"
            )

    def upsert_file(self, workspace_id, fingerprint, tiny_fingerprint, object_key, file_name, file_path):
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO media_files
                (workspace_id, fingerprint, tiny_fingerprint, object_key, file_name, file_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, fingerprint) DO UPDATE SET
                    tiny_fingerprint=excluded.tiny_fingerprint,
                    object_key=excluded.object_key,
                    file_name=excluded.file_name,
                    file_path=excluded.file_path
                """,
                (
                    workspace_id,
                    fingerprint,
                    tiny_fingerprint,
                    object_key,
                    file_name,
                    file_path,
                    int(time.time()),
                ),
            )

    def get_object_key_by_fingerprint(self, workspace_id, fingerprint):
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT object_key FROM media_files WHERE workspace_id=? AND fingerprint=?",
                (workspace_id, fingerprint),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def get_object_key_by_tiny(self, workspace_id, tiny_fingerprint):
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT object_key FROM media_files WHERE workspace_id=? AND tiny_fingerprint=?",
                (workspace_id, tiny_fingerprint),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def delete_by_fingerprint(self, workspace_id, fingerprint):
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM media_files WHERE workspace_id=? AND fingerprint=?",
                (workspace_id, fingerprint),
            )

    def delete_by_tiny(self, workspace_id, tiny_fingerprint):
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM media_files WHERE workspace_id=? AND tiny_fingerprint=?",
                (workspace_id, tiny_fingerprint),
            )

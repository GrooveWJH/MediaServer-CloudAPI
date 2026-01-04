import os
import sqlite3
import time
from contextlib import contextmanager
from queue import Queue


class MediaDB:
    def __init__(self, path, pool_size=4):
        self.path = path
        self._pool = Queue(maxsize=max(1, pool_size))
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        for _ in range(self._pool.maxsize):
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=5)
            conn.execute("PRAGMA busy_timeout = 5000")
            self._pool.put(conn)
        self._init_schema()

    @contextmanager
    def _get_conn(self):
        conn = self._pool.get()
        try:
            yield conn
        finally:
            self._pool.put(conn)

    def _init_schema(self):
        with self._get_conn() as conn:
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
            # media_files is the single source of truth for fingerprints and tiny_fingerprints.

    def close(self):
        while not self._pool.empty():
            conn = self._pool.get_nowait()
            conn.close()

    @contextmanager
    def transaction(self):
        with self._get_conn() as conn:
            try:
                conn.execute("BEGIN")
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def _execute(self, query, params=(), conn=None):
        if conn is None:
            with self._get_conn() as conn_ctx:
                conn_ctx.execute(query, params)
            return
        conn.execute(query, params)

    def _fetch_one(self, query, params=(), conn=None):
        if conn is None:
            with self._get_conn() as conn_ctx:
                cur = conn_ctx.execute(query, params)
                return cur.fetchone()
        cur = conn.execute(query, params)
        return cur.fetchone()

    def upsert_file(self, workspace_id, fingerprint, tiny_fingerprint, object_key, file_name, file_path, conn=None):
        self._execute(
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
            conn=conn,
        )

    def get_object_key_by_fingerprint(self, workspace_id, fingerprint, conn=None):
        row = self._fetch_one(
            "SELECT object_key FROM media_files WHERE workspace_id=? AND fingerprint=?",
            (workspace_id, fingerprint),
            conn=conn,
        )
        if not row:
            return None
        return row[0] or None

    def get_object_key_by_tiny(self, workspace_id, tiny_fingerprint, conn=None):
        row = self._fetch_one(
            "SELECT object_key FROM media_files WHERE workspace_id=? AND tiny_fingerprint=?",
            (workspace_id, tiny_fingerprint),
            conn=conn,
        )
        return row[0] if row else None

    def delete_by_fingerprint(self, workspace_id, fingerprint, conn=None):
        self._execute(
            "DELETE FROM media_files WHERE workspace_id=? AND fingerprint=?",
            (workspace_id, fingerprint),
            conn=conn,
        )

    def delete_by_tiny(self, workspace_id, tiny_fingerprint, conn=None):
        self._execute(
            "DELETE FROM media_files WHERE workspace_id=? AND tiny_fingerprint=?",
            (workspace_id, tiny_fingerprint),
            conn=conn,
        )

    def upsert_fingerprint_tiny(self, workspace_id, fingerprint, tiny_fingerprint, file_name=None, file_path=None, conn=None):
        self._execute(
            """
            INSERT INTO media_files
            (workspace_id, fingerprint, tiny_fingerprint, object_key, file_name, file_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, fingerprint) DO UPDATE SET
                tiny_fingerprint=excluded.tiny_fingerprint,
                object_key=CASE
                    WHEN media_files.object_key IS NOT NULL AND media_files.object_key != '' THEN media_files.object_key
                    ELSE excluded.object_key
                END,
                file_name=excluded.file_name,
                file_path=excluded.file_path
            """,
            (
                workspace_id,
                fingerprint,
                tiny_fingerprint,
                "",
                file_name,
                file_path,
                int(time.time()),
            ),
            conn=conn,
        )

    def get_tiny_by_fingerprint(self, workspace_id, fingerprint, conn=None):
        row = self._fetch_one(
            "SELECT tiny_fingerprint FROM media_files WHERE workspace_id=? AND fingerprint=?",
            (workspace_id, fingerprint),
            conn=conn,
        )
        return row[0] if row else None

import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from queue import Queue


DJI_CAPTURE_TIME_RE = re.compile(
    r"^DJI_(\d{14})_[0-9]{4}_[A-Za-z0-9]+\.[A-Za-z0-9]+$"
)
MEDIA_FILE_EXTRA_COLUMNS = {
    "is_original": "INTEGER",
    "sub_file_type": "TEXT",
    "capture_time": "INTEGER",
    "absolute_altitude": "REAL",
    "relative_altitude": "REAL",
    "gimbal_yaw_degree": "REAL",
    "shoot_position_lat": "REAL",
    "shoot_position_lng": "REAL",
}


class MediaDB:
    def __init__(self, path, pool_size=4):
        self.path = path
        self._pool = Queue(maxsize=max(1, pool_size))
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        for _ in range(self._pool.maxsize):
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=5)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA temp_store = MEMORY")
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
                    is_original INTEGER,
                    sub_file_type TEXT,
                    capture_time INTEGER,
                    absolute_altitude REAL,
                    relative_altitude REAL,
                    gimbal_yaw_degree REAL,
                    shoot_position_lat REAL,
                    shoot_position_lng REAL,
                    created_at INTEGER NOT NULL,
                    UNIQUE(workspace_id, fingerprint)
                )
                """
            )
            existing_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(media_files)").fetchall()
            }
            for name, column_type in MEDIA_FILE_EXTRA_COLUMNS.items():
                if name in existing_columns:
                    continue
                conn.execute(f"ALTER TABLE media_files ADD COLUMN {name} {column_type}")
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

    def _extract_capture_timestamp(self, file_name=None, object_key=None):
        candidates = [file_name, object_key]
        for candidate in candidates:
            if not candidate:
                continue
            base_name = os.path.basename(str(candidate).strip())
            match = DJI_CAPTURE_TIME_RE.match(base_name)
            if not match:
                continue
            try:
                dt = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
            except ValueError:
                continue
            return int(time.mktime(dt.timetuple()))
        return None

    def _resolve_created_at(self, file_name=None, object_key=None):
        parsed = self._extract_capture_timestamp(file_name=file_name, object_key=object_key)
        if parsed is not None:
            return parsed, True
        return int(time.time()), False

    def _coerce_bool_int(self, value):
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(bool(value))
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return 1
            if lowered in {"false", "0", "no", "n"}:
                return 0
        return None

    def _coerce_float(self, value):
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _coerce_timestamp(self, value):
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return int(value.timestamp())
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.isdigit():
                return int(text)
            try:
                return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
            except ValueError:
                return None
        return None

    def _resolve_media_metadata_fields(
        self,
        *,
        is_original=None,
        sub_file_type=None,
        capture_time=None,
        absolute_altitude=None,
        relative_altitude=None,
        gimbal_yaw_degree=None,
        shoot_position_lat=None,
        shoot_position_lng=None,
        metadata=None,
    ):
        metadata = metadata if isinstance(metadata, dict) else {}
        shoot_position = metadata.get("shoot_position")
        if not isinstance(shoot_position, dict):
            shoot_position = {}
        return {
            "is_original": self._coerce_bool_int(is_original),
            "sub_file_type": None if sub_file_type in {None, ""} else str(sub_file_type),
            "capture_time": self._coerce_timestamp(
                capture_time if capture_time is not None else metadata.get("created_time")
            ),
            "absolute_altitude": self._coerce_float(
                absolute_altitude if absolute_altitude is not None else metadata.get("absolute_altitude")
            ),
            "relative_altitude": self._coerce_float(
                relative_altitude if relative_altitude is not None else metadata.get("relative_altitude")
            ),
            "gimbal_yaw_degree": self._coerce_float(
                gimbal_yaw_degree if gimbal_yaw_degree is not None else metadata.get("gimbal_yaw_degree")
            ),
            "shoot_position_lat": self._coerce_float(
                shoot_position_lat if shoot_position_lat is not None else shoot_position.get("lat")
            ),
            "shoot_position_lng": self._coerce_float(
                shoot_position_lng if shoot_position_lng is not None else shoot_position.get("lng")
            ),
        }

    def upsert_file(
        self,
        workspace_id,
        fingerprint,
        tiny_fingerprint,
        object_key,
        file_name,
        file_path,
        is_original=None,
        sub_file_type=None,
        capture_time=None,
        absolute_altitude=None,
        relative_altitude=None,
        gimbal_yaw_degree=None,
        shoot_position_lat=None,
        shoot_position_lng=None,
        metadata=None,
        conn=None,
    ):
        created_at, parsed_from_name = self._resolve_created_at(file_name=file_name, object_key=object_key)
        extra_fields = self._resolve_media_metadata_fields(
            is_original=is_original,
            sub_file_type=sub_file_type,
            capture_time=capture_time,
            absolute_altitude=absolute_altitude,
            relative_altitude=relative_altitude,
            gimbal_yaw_degree=gimbal_yaw_degree,
            shoot_position_lat=shoot_position_lat,
            shoot_position_lng=shoot_position_lng,
            metadata=metadata,
        )
        self._execute(
            """
            INSERT INTO media_files
            (
                workspace_id, fingerprint, tiny_fingerprint, object_key, file_name, file_path,
                is_original, sub_file_type, capture_time, absolute_altitude, relative_altitude,
                gimbal_yaw_degree, shoot_position_lat, shoot_position_lng, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, fingerprint) DO UPDATE SET
                tiny_fingerprint=excluded.tiny_fingerprint,
                object_key=excluded.object_key,
                file_name=excluded.file_name,
                file_path=excluded.file_path,
                is_original=excluded.is_original,
                sub_file_type=excluded.sub_file_type,
                capture_time=excluded.capture_time,
                absolute_altitude=excluded.absolute_altitude,
                relative_altitude=excluded.relative_altitude,
                gimbal_yaw_degree=excluded.gimbal_yaw_degree,
                shoot_position_lat=excluded.shoot_position_lat,
                shoot_position_lng=excluded.shoot_position_lng,
                created_at=CASE
                    WHEN ? THEN ?
                    ELSE media_files.created_at
                END
            """,
            (
                workspace_id,
                fingerprint,
                tiny_fingerprint,
                object_key,
                file_name,
                file_path,
                extra_fields["is_original"],
                extra_fields["sub_file_type"],
                extra_fields["capture_time"],
                extra_fields["absolute_altitude"],
                extra_fields["relative_altitude"],
                extra_fields["gimbal_yaw_degree"],
                extra_fields["shoot_position_lat"],
                extra_fields["shoot_position_lng"],
                created_at,
                int(parsed_from_name),
                created_at,
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

    def upsert_fingerprint_tiny(
        self,
        workspace_id,
        fingerprint,
        tiny_fingerprint,
        file_name=None,
        file_path=None,
        is_original=None,
        sub_file_type=None,
        capture_time=None,
        absolute_altitude=None,
        relative_altitude=None,
        gimbal_yaw_degree=None,
        shoot_position_lat=None,
        shoot_position_lng=None,
        metadata=None,
        conn=None,
    ):
        created_at, parsed_from_name = self._resolve_created_at(file_name=file_name)
        extra_fields = self._resolve_media_metadata_fields(
            is_original=is_original,
            sub_file_type=sub_file_type,
            capture_time=capture_time,
            absolute_altitude=absolute_altitude,
            relative_altitude=relative_altitude,
            gimbal_yaw_degree=gimbal_yaw_degree,
            shoot_position_lat=shoot_position_lat,
            shoot_position_lng=shoot_position_lng,
            metadata=metadata,
        )
        self._execute(
            """
            INSERT INTO media_files
            (
                workspace_id, fingerprint, tiny_fingerprint, object_key, file_name, file_path,
                is_original, sub_file_type, capture_time, absolute_altitude, relative_altitude,
                gimbal_yaw_degree, shoot_position_lat, shoot_position_lng, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, fingerprint) DO UPDATE SET
                tiny_fingerprint=excluded.tiny_fingerprint,
                object_key=CASE
                    WHEN media_files.object_key IS NOT NULL AND media_files.object_key != '' THEN media_files.object_key
                    ELSE excluded.object_key
                END,
                file_name=excluded.file_name,
                file_path=excluded.file_path,
                is_original=excluded.is_original,
                sub_file_type=excluded.sub_file_type,
                capture_time=excluded.capture_time,
                absolute_altitude=excluded.absolute_altitude,
                relative_altitude=excluded.relative_altitude,
                gimbal_yaw_degree=excluded.gimbal_yaw_degree,
                shoot_position_lat=excluded.shoot_position_lat,
                shoot_position_lng=excluded.shoot_position_lng,
                created_at=CASE
                    WHEN ? THEN ?
                    ELSE media_files.created_at
                END
            """,
            (
                workspace_id,
                fingerprint,
                tiny_fingerprint,
                "",
                file_name,
                file_path,
                extra_fields["is_original"],
                extra_fields["sub_file_type"],
                extra_fields["capture_time"],
                extra_fields["absolute_altitude"],
                extra_fields["relative_altitude"],
                extra_fields["gimbal_yaw_degree"],
                extra_fields["shoot_position_lat"],
                extra_fields["shoot_position_lng"],
                created_at,
                int(parsed_from_name),
                created_at,
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

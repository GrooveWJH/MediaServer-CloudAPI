import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

WEB_ROOT = REPO_ROOT / "web"
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from media_server.http_layer.request_models import parse_fast_upload, parse_upload_callback
from media_server.storage.db import MediaDB
from app import WebConfig, create_app


class RequestModelMetadataTest(unittest.TestCase):
    def test_parse_fast_upload_keeps_is_original_and_metadata(self):
        payload = {
            "fingerprint": "fp-1",
            "name": "DJI_20240102112233_0001_W.JPG",
            "path": "/DCIM/100MEDIA/DJI_20240102112233_0001_W.JPG",
            "sub_file_type": "PANORAMA",
            "ext": {
                "tinny_fingerprint": "tiny-1",
                "is_original": True,
            },
            "metadata": {
                "created_time": "2024-01-02T11:22:33Z",
                "absolute_altitude": 120.5,
                "relative_altitude": 20.25,
                "gimbal_yaw_degree": -45.0,
                "shoot_position": {
                    "lat": 31.2304,
                    "lng": 121.4737,
                },
            },
        }

        req, err = parse_fast_upload(payload)

        self.assertIsNone(err)
        self.assertEqual(True, req.is_original)
        self.assertEqual("PANORAMA", req.sub_file_type)
        self.assertEqual("2024-01-02T11:22:33Z", req.metadata["created_time"])
        self.assertEqual(31.2304, req.metadata["shoot_position"]["lat"])

    def test_parse_upload_callback_keeps_protocol_fields(self):
        payload = {
            "object_key": "media/test.jpg",
            "fingerprint": "fp-2",
            "tinny_fingerprint": "tiny-2",
            "name": "DJI_20240102112233_0001_W.JPG",
            "path": "/DCIM/100MEDIA/DJI_20240102112233_0001_W.JPG",
            "sub_file_type": 3,
            "ext": {
                "is_original": False,
            },
            "metadata": {
                "created_time": "2024-01-02T11:22:33Z",
                "shoot_position": {
                    "lat": 22.5431,
                    "lng": 114.0579,
                },
            },
        }

        req, err = parse_upload_callback(payload)

        self.assertIsNone(err)
        self.assertEqual(False, req.is_original)
        self.assertEqual("3", req.sub_file_type)
        self.assertEqual(22.5431, req.metadata["shoot_position"]["lat"])


class MediaDBMetadataTest(unittest.TestCase):
    def test_init_schema_migrates_existing_media_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "media.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE media_files (
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
            conn.commit()
            conn.close()

            db = MediaDB(str(db_path))
            db.close()

            conn = sqlite3.connect(db_path)
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(media_files)").fetchall()
            }
            conn.close()

            self.assertTrue(
                {
                    "is_original",
                    "sub_file_type",
                    "capture_time",
                    "absolute_altitude",
                    "relative_altitude",
                    "gimbal_yaw_degree",
                    "shoot_position_lat",
                    "shoot_position_lng",
                }.issubset(columns)
            )

    def test_upsert_file_persists_metadata_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "media.db"
            db = MediaDB(str(db_path))

            db.upsert_file(
                "ws-1",
                "fp-3",
                "tiny-3",
                "media/test.jpg",
                "DJI_20240102112233_0001_W.JPG",
                "/DCIM/100MEDIA/DJI_20240102112233_0001_W.JPG",
                is_original=True,
                sub_file_type="PANORAMA",
                capture_time=1704194553,
                absolute_altitude=100.5,
                relative_altitude=50.25,
                gimbal_yaw_degree=-90.0,
                shoot_position_lat=31.2304,
                shoot_position_lng=121.4737,
            )

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT is_original, sub_file_type, capture_time, absolute_altitude,
                           relative_altitude, gimbal_yaw_degree, shoot_position_lat, shoot_position_lng
                    FROM media_files
                    WHERE workspace_id=? AND fingerprint=?
                    """,
                    ("ws-1", "fp-3"),
                ).fetchone()

            db.close()

            self.assertEqual((1, "PANORAMA", 1704194553), row[:3])
            self.assertEqual((100.5, 50.25, -90.0, 31.2304, 121.4737), row[3:])


class WebMediaMetadataTest(unittest.TestCase):
    def test_api_media_returns_new_metadata_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "media.db"
            db = MediaDB(str(db_path))
            db.upsert_file(
                "ws-2",
                "fp-4",
                "tiny-4",
                "media/test.jpg",
                "DJI_20240102112233_0001_W.JPG",
                "/DCIM/100MEDIA/DJI_20240102112233_0001_W.JPG",
                is_original=False,
                sub_file_type="THERMAL",
                capture_time=1704165753,
                absolute_altitude=180.0,
                relative_altitude=80.0,
                gimbal_yaw_degree=15.5,
                shoot_position_lat=30.5728,
                shoot_position_lng=104.0668,
            )

            app = create_app(
                WebConfig(
                    host="127.0.0.1",
                    port=8088,
                    db_path=str(db_path),
                    storage_endpoint="http://127.0.0.1:9000",
                    storage_bucket="media",
                    storage_region="us-east-1",
                    storage_access_key="minioadmin",
                    storage_secret_key="minioadmin",
                    storage_session_token="",
                )
            )
            client = app.test_client()

            response = client.get("/api/media")
            payload = response.get_json()
            item = payload["items"][0]

            db.close()

            self.assertEqual(200, response.status_code)
            self.assertEqual("THERMAL", item["sub_file_type"])
            self.assertEqual("非原图", item["is_original_label"])
            self.assertEqual("2024-01-02 11:22:33", item["capture_time"])
            self.assertEqual(30.5728, item["shoot_position_lat"])
            self.assertEqual(104.0668, item["shoot_position_lng"])

    def test_index_renders_metadata_labels_and_empty_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "media.db"
            db = MediaDB(str(db_path))
            db.upsert_file(
                "ws-3",
                "fp-5",
                "tiny-5",
                "media/test.jpg",
                "DJI_20240102112233_0001_W.JPG",
                "/DCIM/100MEDIA/DJI_20240102112233_0001_W.JPG",
                is_original=True,
                sub_file_type=None,
                capture_time=None,
                absolute_altitude=None,
                relative_altitude=12.0,
                gimbal_yaw_degree=None,
                shoot_position_lat=None,
                shoot_position_lng=None,
            )

            app = create_app(
                WebConfig(
                    host="127.0.0.1",
                    port=8088,
                    db_path=str(db_path),
                    storage_endpoint="http://127.0.0.1:9000",
                    storage_bucket="media",
                    storage_region="us-east-1",
                    storage_access_key="minioadmin",
                    storage_secret_key="minioadmin",
                    storage_session_token="",
                )
            )
            client = app.test_client()

            response = client.get("/")
            html = response.get_data(as_text=True)

            db.close()

            self.assertEqual(200, response.status_code)
            self.assertIn("原图标记：</strong>原图", html)
            self.assertIn("子文件类型：</strong>-", html)
            self.assertIn("相对高度：</strong>12.0 m", html)
            self.assertIn("拍摄位置：</strong>-", html)


if __name__ == "__main__":
    unittest.main()

"""
Google Drive sync for SQLite DB.

On startup: download DB from Drive.
After every commit: schedule an upload (debounced 5 s) in a background thread.

Set env vars:
  DRIVE_FILE_ID              – Google Drive file ID of asset_manager.db
  GOOGLE_SERVICE_ACCOUNT_JSON – base64-encoded service-account JSON key
                                (or set GOOGLE_APPLICATION_CREDENTIALS to a file path)

If neither is set the module is a no-op, so local dev works without credentials.
"""

import base64
import io
import json
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

_DRIVE_FILE_ID = os.environ.get("DRIVE_FILE_ID", "")
_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

_upload_timer: threading.Timer | None = None
_upload_lock = threading.Lock()
_local_db_path: str = ""
_drive_service = None


# ---------------------------------------------------------------------------
# Service initialisation
# ---------------------------------------------------------------------------

def _build_service():
    """Build and return a Google Drive API service object, or None if not configured."""
    global _drive_service
    if _drive_service is not None:
        return _drive_service

    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        import google.auth

        sa_json_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if sa_json_b64:
            sa_info = json.loads(base64.b64decode(sa_json_b64).decode())
            creds = service_account.Credentials.from_service_account_info(
                sa_info, scopes=_SCOPES
            )
        else:
            # Fall back to GOOGLE_APPLICATION_CREDENTIALS file or ADC
            creds, _ = google.auth.default(scopes=_SCOPES)

        _drive_service = build("drive", "v3", credentials=creds)
        return _drive_service
    except Exception as exc:
        log.warning("Drive sync disabled — could not build service: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Download / Upload
# ---------------------------------------------------------------------------

def download_db(local_path: str) -> bool:
    """
    Download the DB file from Drive to local_path.
    Returns True on success, False if Drive is not configured or download fails.
    """
    if not _DRIVE_FILE_ID:
        return False
    service = _build_service()
    if service is None:
        return False

    try:
        from googleapiclient.http import MediaIoBaseDownload

        request = service.files().get_media(fileId=_DRIVE_FILE_ID)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(buf.getvalue())

        log.info("Downloaded DB from Drive (%d bytes)", len(buf.getvalue()))
        return True
    except Exception as exc:
        log.error("Drive download failed: %s", exc)
        return False


def upload_db(local_path: str) -> bool:
    """Upload the local DB file back to Drive. Returns True on success."""
    if not _DRIVE_FILE_ID:
        return False
    service = _build_service()
    if service is None:
        return False

    try:
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(local_path, mimetype="application/x-sqlite3", resumable=False)
        service.files().update(fileId=_DRIVE_FILE_ID, media_body=media).execute()
        log.info("Uploaded DB to Drive")
        return True
    except Exception as exc:
        log.error("Drive upload failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Debounced background upload
# ---------------------------------------------------------------------------

def _do_upload():
    global _upload_timer
    with _upload_lock:
        _upload_timer = None
    if _local_db_path:
        upload_db(_local_db_path)


def schedule_upload(local_path: str, delay: float = 5.0) -> None:
    """Schedule a DB upload to Drive after `delay` seconds (debounced)."""
    global _upload_timer, _local_db_path
    _local_db_path = local_path
    with _upload_lock:
        if _upload_timer is not None:
            _upload_timer.cancel()
        _upload_timer = threading.Timer(delay, _do_upload)
        _upload_timer.daemon = True
        _upload_timer.start()


# ---------------------------------------------------------------------------
# Patched connection wrapper
# ---------------------------------------------------------------------------

def make_syncing_connection(conn, local_path: str):
    """
    Monkey-patch conn.commit() so every commit schedules a Drive upload.
    Returns the same conn object (mutated in place).
    """
    original_commit = conn.commit

    def _commit():
        original_commit()
        schedule_upload(local_path)

    conn.commit = _commit
    return conn

"""Shared FastAPI dependencies."""

import os
import sqlite3
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db.connection import get_connection

_API_TOKEN = os.environ.get("API_TOKEN", "")

_bearer = HTTPBearer(auto_error=False)


def verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)] = None,
) -> None:
    """Require Bearer token when API_TOKEN env var is set."""
    if not _API_TOKEN:
        return  # no token configured — open access (rely on IAP)
    if credentials is None or credentials.credentials != _API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


def get_db() -> sqlite3.Connection:
    """Return the shared SQLite connection (Drive-sync patched)."""
    return get_connection()

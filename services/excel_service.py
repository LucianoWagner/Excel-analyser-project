"""
Excel service — parses, stores, and manages Excel sessions in memory
with automatic expiration and maximum session limits.
"""

import logging
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import HTTPException, UploadFile, status

from config import settings
from models import SheetInfo

logger = logging.getLogger(__name__)


def _classify_dtype(dtype) -> str:
    """Classify a pandas dtype into a simple category."""
    name = str(dtype)
    if "int" in name or "float" in name:
        return "numeric"
    if "bool" in name:
        return "bool"
    if "datetime" in name or "date" in name:
        return "date"
    return "text"


# ══════════════════════════════════════════════════
#  Session Store with TTL
# ══════════════════════════════════════════════════

class SessionStore:
    """In-memory session store with TTL and max capacity."""

    def __init__(self, ttl_minutes: int, max_sessions: int):
        self._sessions: dict[str, dict] = {}
        self._ttl = timedelta(minutes=ttl_minutes)
        self._max_sessions = max_sessions

    def _cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count of removed."""
        now = datetime.now()
        expired = [
            sid for sid, data in self._sessions.items()
            if now - data["last_access"] > self._ttl
        ]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            logger.info("Cleaned up %d expired session(s)", len(expired))
        return len(expired)

    def create(self, filename: str, sheets: dict[str, pd.DataFrame]) -> str:
        """Store a new session. Cleans up expired first, enforces max capacity."""
        self._cleanup_expired()

        # Enforce max sessions
        if len(self._sessions) >= self._max_sessions:
            # Remove the oldest session
            oldest_sid = min(self._sessions, key=lambda s: self._sessions[s]["last_access"])
            logger.warning("Max sessions (%d) reached. Removing oldest: %s", self._max_sessions, oldest_sid)
            del self._sessions[oldest_sid]

        session_id = str(uuid.uuid4())
        self._sessions[session_id] = {
            "filename": filename,
            "sheets": sheets,
            "created_at": datetime.now(),
            "last_access": datetime.now(),
        }
        logger.info("Session created: %s (%s) — Active: %d", session_id[:8], filename, len(self._sessions))
        return session_id

    def get(self, session_id: str) -> dict | None:
        """Get a session and refresh its last_access timestamp."""
        self._cleanup_expired()
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session["last_access"] = datetime.now()
        return session

    def info(self) -> dict:
        """Return info about active sessions (for debugging)."""
        self._cleanup_expired()
        return {
            "active_sessions": len(self._sessions),
            "max_sessions": self._max_sessions,
            "ttl_minutes": self._ttl.total_seconds() / 60,
            "sessions": {
                sid: {
                    "filename": data["filename"],
                    "sheets": list(data["sheets"].keys()),
                    "created_at": data["created_at"].isoformat(),
                    "last_access": data["last_access"].isoformat(),
                }
                for sid, data in self._sessions.items()
            },
        }


# Singleton instance
_store = SessionStore(
    ttl_minutes=settings.session_ttl_minutes,
    max_sessions=settings.max_sessions,
)


# ══════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════

async def parse_and_store_excel(file: UploadFile) -> tuple[str, list[SheetInfo]]:
    """
    Validate, parse all sheets from the uploaded Excel file,
    store in memory, and return session_id + sheet info.
    """
    # Validate extension
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nombre de archivo vacío")

    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if extension not in ("xlsx", "xls"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato no soportado: .{extension}. Solo se aceptan .xlsx y .xls",
        )

    # Read file content
    content = await file.read()

    # Validate size
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Archivo demasiado grande: {size_mb:.1f}MB. Máximo: {settings.max_file_size_mb}MB",
        )

    # Parse all sheets
    try:
        all_sheets: dict[str, pd.DataFrame] = pd.read_excel(
            BytesIO(content), sheet_name=None, engine="openpyxl"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error al leer el archivo Excel: {str(e)}",
        )

    # Validate row limits per sheet
    sheets_info: list[SheetInfo] = []
    for sheet_name, df in all_sheets.items():
        if len(df) > settings.max_rows:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La sheet '{sheet_name}' tiene {len(df)} filas. Máximo: {settings.max_rows}",
            )
        sheets_info.append(SheetInfo(
            name=str(sheet_name),
            rows=len(df),
            columns=len(df.columns),
            column_names=list(df.columns.astype(str)),
            column_types=[_classify_dtype(df[col].dtype) for col in df.columns],
        ))

    # Store in memory (with TTL)
    session_id = _store.create(file.filename, all_sheets)
    return session_id, sheets_info


def get_dataframe(session_id: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
    """
    Retrieve a DataFrame from the session store.
    If sheet_name is None, returns the first sheet.
    Always returns a deep copy.
    """
    session = _store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesión no encontrada o expirada: {session_id}. Subí el archivo de nuevo.",
        )

    sheets = session["sheets"]

    if sheet_name is None:
        first_key = next(iter(sheets))
        return sheets[first_key].copy(deep=True)

    if sheet_name not in sheets:
        available = ", ".join(sheets.keys())
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sheet '{sheet_name}' no encontrada. Sheets disponibles: {available}",
        )

    return sheets[sheet_name].copy(deep=True)


def list_sessions() -> dict:
    """Return info about active sessions (for debugging)."""
    return _store.info()

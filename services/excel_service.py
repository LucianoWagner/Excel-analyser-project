"""
Excel service — parses, stores, and manages Excel sessions in memory
with automatic expiration, maximum session limits, and version history.
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

# Maximum number of saved versions per sheet (original + N modifications)
_MAX_VERSIONS = 3  # original + 2 modifications


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
#  Session Store with TTL + Version History
# ══════════════════════════════════════════════════

class SessionStore:
    """In-memory session store with TTL, max capacity, and DataFrame version history."""

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
            oldest_sid = min(self._sessions, key=lambda s: self._sessions[s]["last_access"])
            logger.warning("Max sessions (%d) reached. Removing oldest: %s", self._max_sessions, oldest_sid)
            del self._sessions[oldest_sid]

        session_id = str(uuid.uuid4())

        # Build version history: one "Original" entry per sheet
        versions: dict[str, list[dict]] = {
            sheet_name: [
                {
                    "label": "Original",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "df": df.copy(deep=True),
                }
            ]
            for sheet_name, df in sheets.items()
        }

        self._sessions[session_id] = {
            "filename": filename,
            "sheets": {k: v.copy(deep=True) for k, v in sheets.items()},  # current (mutable)
            "versions": versions,
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

    def add_version(self, session_id: str, sheet_name: str, df: pd.DataFrame) -> None:
        """
        Save a new version of a sheet's DataFrame.
        Keeps original + up to (_MAX_VERSIONS - 1) modifications.
        If limit is reached, drops the oldest modification (not the original).
        """
        session = self._sessions.get(session_id)
        if session is None:
            return

        versions = session["versions"].setdefault(sheet_name, [])

        # Keep original always at index 0; trim modifications if over limit
        if len(versions) >= _MAX_VERSIONS:
            # Remove index 1 (oldest modification, preserving original at 0)
            versions.pop(1)

        versions.append({
            "label": f"v{len(versions)} · {datetime.now().strftime('%H:%M:%S')}",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "df": df.copy(deep=True),
        })

        # Update the "current" sheet to the new version
        session["sheets"][sheet_name] = df.copy(deep=True)
        logger.info("Version saved for session %s, sheet=%s — total versions: %d",
                    session_id[:8], sheet_name, len(versions))

    def get_versions(self, session_id: str, sheet_name: str) -> list[dict]:
        """
        Return version metadata (without the full DataFrame) for a sheet.
        Each entry: {index, label, timestamp, rows, columns, preview}
        """
        session = self._sessions.get(session_id)
        if session is None:
            return []

        versions = session.get("versions", {}).get(sheet_name, [])
        result = []
        for i, v in enumerate(versions):
            df = v["df"]
            result.append({
                "index": i,
                "label": v["label"],
                "timestamp": v["timestamp"],
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": list(df.columns.astype(str)),
                "preview": df.head(8).fillna("").astype(str).to_dict(orient="records"),
            })
        return result

    def get_version_df(self, session_id: str, sheet_name: str, version_idx: int) -> pd.DataFrame | None:
        """Return a specific version of a sheet as a DataFrame copy."""
        session = self._sessions.get(session_id)
        if session is None:
            return None

        versions = session.get("versions", {}).get(sheet_name, [])
        if version_idx < 0 or version_idx >= len(versions):
            return None

        return versions[version_idx]["df"].copy(deep=True)

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
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nombre de archivo vacío")

    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if extension not in ("xlsx", "xls"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato no soportado: .{extension}. Solo se aceptan .xlsx y .xls",
        )

    content = await file.read()

    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Archivo demasiado grande: {size_mb:.1f}MB. Máximo: {settings.max_file_size_mb}MB",
        )

    try:
        all_sheets: dict[str, pd.DataFrame] = pd.read_excel(
            BytesIO(content), sheet_name=None, engine="openpyxl"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error al leer el archivo Excel: {str(e)}",
        )

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

    session_id = _store.create(file.filename, all_sheets)
    return session_id, sheets_info


def get_dataframe(session_id: str, sheet_name: Optional[str] = None) -> tuple[pd.DataFrame, str]:
    """
    Retrieve the current DataFrame from the session store.
    Returns (df_copy, resolved_sheet_name).
    """
    session = _store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesión no encontrada o expirada: {session_id}. Subí el archivo de nuevo.",
        )

    sheets = session["sheets"]

    if sheet_name is None:
        sheet_name = next(iter(sheets))

    if sheet_name not in sheets:
        available = ", ".join(sheets.keys())
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sheet '{sheet_name}' no encontrada. Sheets disponibles: {available}",
        )

    return sheets[sheet_name].copy(deep=True), sheet_name


def save_version(session_id: str, sheet_name: str, df: pd.DataFrame) -> None:
    """Save a new version of a sheet's DataFrame to the session version history."""
    _store.add_version(session_id, sheet_name, df)


def get_versions(session_id: str, sheet_name: str) -> list[dict]:
    """Return all saved versions (metadata + preview) for a sheet."""
    return _store.get_versions(session_id, sheet_name)


def get_version_df(session_id: str, sheet_name: str, version_idx: int) -> pd.DataFrame | None:
    """Return a specific version DataFrame by index."""
    return _store.get_version_df(session_id, sheet_name, version_idx)


def list_sessions() -> dict:
    """Return info about active sessions."""
    return _store.info()

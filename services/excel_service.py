import uuid
from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import HTTPException, UploadFile, status

from config import settings
from models import SheetInfo

# ── In-memory session store ──
# Key: session_id → Value: {"filename": str, "sheets": dict[str, DataFrame]}
_sessions: dict[str, dict] = {}


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
        ))

    # Store in memory
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "filename": file.filename,
        "sheets": all_sheets,
    }

    return session_id, sheets_info


def get_dataframe(session_id: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
    """
    Retrieve a DataFrame from the session store.
    If sheet_name is None, returns the first sheet.
    Always returns a deep copy.
    """
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesión no encontrada: {session_id}. ¿Ya subiste un archivo?",
        )

    sheets = session["sheets"]

    if sheet_name is None:
        # Return first sheet
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
    return {
        sid: {
            "filename": data["filename"],
            "sheets": list(data["sheets"].keys()),
        }
        for sid, data in _sessions.items()
    }

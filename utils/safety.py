"""Utility validations and safety checks."""

import re
from fastapi import UploadFile, HTTPException, status
from config import settings


BLOCKED_PATTERNS = [
    r"\bos\.",
    r"\bsubprocess\b",
    r"\b__import__\b",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bopen\s*\(",
    r"\bsystem\s*\(",
    r"\brmtree\b",
    r"\bunlink\b",
    r"\bshutil\b",
    r"\bpickle\b",
    r"\brequests\b",
    r"\burllib\b",
    r"\bsocket\b",
]


def check_code_safety(code: str) -> tuple[bool, str | None]:
    """
    Check generated code for dangerous patterns.
    Returns (is_safe, violation_description).
    """
    for pattern in BLOCKED_PATTERNS:
        match = re.search(pattern, code)
        if match:
            return False, f"Código bloqueado: patrón peligroso detectado '{match.group()}'"
    return True, None


def validate_upload_file(file: UploadFile) -> None:
    """Validate the uploaded file's name and extension."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nombre de archivo vacío",
        )

    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if extension not in ("xlsx", "xls"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato no soportado: .{extension}. Solo se aceptan .xlsx y .xls",
        )

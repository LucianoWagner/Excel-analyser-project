"""Security validations: code safety checks and prompt injection detection."""

import re
from fastapi import UploadFile, HTTPException, status
from config import settings


# ══════════════════════════════════════════════════
#  Code Safety — check generated code before exec()
# ══════════════════════════════════════════════════

BLOCKED_CODE_PATTERNS = [
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
    r"\bcompile\b",
    r"\bglobals\s*\(",
    r"\blocals\s*\(",
    r"\b__builtins__\b",
    r"\bbreakpoint\s*\(",
    r"\binput\s*\(",
]


def check_code_safety(code: str) -> tuple[bool, str | None]:
    """
    Check generated code for dangerous patterns.
    Returns (is_safe, violation_description).
    """
    for pattern in BLOCKED_CODE_PATTERNS:
        match = re.search(pattern, code)
        if match:
            return False, f"Código bloqueado: patrón peligroso detectado '{match.group()}'"
    return True, None


# ══════════════════════════════════════════════════
#  Prompt Injection Detection — check user questions
# ══════════════════════════════════════════════════

BLOCKED_PROMPT_PATTERNS = [
    # Direct code injection attempts
    r"\bos\.system\b",
    r"\bsubprocess\b",
    r"\b__import__\b",
    r"\bexec\s*\(",
    r"\beval\s*\(",
    r"\bopen\s*\(",
    r"\bsystem\s*\(",
    r"\brm\s+-rf\b",
    r"\bdel\s+\w+\b",
    # Instruction override attempts (Spanish + English)
    r"ignor[áa]\s+(?:todas\s+(?:las|tus)\s+|todas\s+|tus\s+|las\s+)?(?:reglas|instrucciones|restricciones)",
    r"olvi[dá]a(te)?\s+(?:de\s+)?(?:todas\s+(?:las|tus)\s+|todas\s+|tus\s+|las\s+)?(?:reglas|instrucciones|restricciones)",
    r"ignore\s+(your|all|previous)\s+(rules|instructions|restrictions)",
    r"forget\s+(your|all|previous)\s+(rules|instructions)",
    r"override\s+(your|all|previous)\s+(rules|instructions|safety)",
    r"disregard\s+(your|all|previous)\s+(rules|instructions)",
    r"act\s+as\s+(if|a)\b",
    r"pretend\s+(you|to)\b",
    r"jailbreak",
    r"DAN\s+mode",
    # File system access
    r"\b/etc/passwd\b",
    r"\b/etc/shadow\b",
    r"\.env\b",
    r"environment\s+variables?\b",
    r"api[_\s]?key\b",
    r"secret[_\s]?key\b",
]


def check_prompt_safety(question: str) -> tuple[bool, str | None]:
    """
    Check user question for prompt injection patterns.
    Returns (is_safe, violation_description).
    """
    for pattern in BLOCKED_PROMPT_PATTERNS:
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            return False, f"Consulta bloqueada: patrón sospechoso detectado"
    return True, None


# ══════════════════════════════════════════════════
#  File Upload Validation
# ══════════════════════════════════════════════════

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

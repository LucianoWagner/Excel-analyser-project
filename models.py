from pydantic import BaseModel, Field
from typing import Optional


# ── Auth ──

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


# ── Upload ──

class SheetInfo(BaseModel):
    name: str
    rows: int
    columns: int
    column_names: list[str]
    column_types: list[str]  # "numeric" | "text" | "bool" | "date"


class UploadResponse(BaseModel):
    session_id: str
    filename: str
    sheets: list[SheetInfo]


# ── Query ──

class QueryRequest(BaseModel):
    session_id: str
    question: str = Field(..., min_length=1, max_length=2000)
    sheet_name: Optional[str] = None  # None = first sheet


class QueryResponse(BaseModel):
    answer: str
    chart_base64: Optional[str] = None
    code_generated: Optional[str] = None  # only in agent mode
    operation_used: Optional[str] = None  # only in structured mode
    mode: str  # "agent" | "structured"

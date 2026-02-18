from fastapi import APIRouter, Depends, UploadFile, File

from auth import get_current_user, CurrentUser
from models import UploadResponse
from services.excel_service import parse_and_store_excel

router = APIRouter(tags=["Upload"])


@router.post("/upload", response_model=UploadResponse)
async def upload_excel(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Upload an Excel file (.xlsx / .xls).
    Returns a session_id and information about all sheets found.
    """
    session_id, sheets_info = await parse_and_store_excel(file)
    return UploadResponse(
        session_id=session_id,
        filename=file.filename or "unknown",
        sheets=sheets_info,
    )

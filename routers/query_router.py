import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from auth import get_current_user, CurrentUser
from config import settings
from models import QueryRequest, QueryResponse
from services.excel_service import get_dataframe
from services.agent_service import query_with_agent
from services.structured_service import query_structured

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Query"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/query", response_model=QueryResponse)
@limiter.limit(settings.rate_limit_query)
async def query_excel(
    request: Request,
    req: QueryRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Ask a question about the uploaded Excel.
    - Admin → Pandas Agent (full code gen + charts)
    - User  → Structured intent router (predefined operations)
    """
    # Get a deep copy of the DataFrame
    df = get_dataframe(req.session_id, req.sheet_name)

    try:
        if user.is_admin:
            logger.info(f"[AGENT MODE] user={user.username} question='{req.question[:80]}'")
            result = await query_with_agent(df, req.question)
        else:
            logger.info(f"[STRUCTURED MODE] user={user.username} question='{req.question[:80]}'")
            result = await query_structured(df, req.question)
    except TimeoutError as e:
        raise HTTPException(status_code=status.HTTP_408_REQUEST_TIMEOUT, detail=str(e))
    except Exception as e:
        logger.error(f"Query error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al procesar la consulta: {str(e)}",
        )

    return result

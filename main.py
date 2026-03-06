import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import settings
from database import create_tables, async_session
from auth import create_default_admin
from routers import auth_router, upload_router, query_router

# ── Logging ──
# JSON logs in production, human-readable in development
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log["exception"] = self.formatException(record.exc_info)
        return json.dumps(log)


def setup_logging():
    log_format = os.getenv("LOG_FORMAT", "text")  # "json" for production
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
            datefmt="%H:%M:%S",
        ))
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)


setup_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# ── Rate Limiter (singleton, shared across routers) ──
limiter = Limiter(key_func=get_remote_address)


# ── Lifespan ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables + default admin. Shutdown: cleanup."""
    logger.info(">> Iniciando Chat con tu Excel...")

    # Create DB tables
    await create_tables()
    logger.info("[OK] Tablas de la base de datos creadas/verificadas")

    # Create default admin
    async with async_session() as db:
        await create_default_admin(db)

    logger.info("[OK] Servidor listo")
    yield
    logger.info("[--] Servidor detenido")


# ── App ──
app = FastAPI(
    title="Chat con tu Excel",
    description=(
        "Backend para consultar archivos Excel en lenguaje natural. "
        "Modo Admin (Pandas Agent) y Modo Usuario (funciones predefinidas)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── Rate Limiter state ──
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──
app.include_router(auth_router.router)
app.include_router(upload_router.router)
app.include_router(query_router.router)

# ── Static files ──
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Root → Frontend ──
@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── Health ──
@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "Chat con tu Excel"}

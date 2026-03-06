from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # ── LLM ──
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # ── Database ──
    database_url: str = "postgresql+asyncpg://excel_user:excel_pass_2024@localhost:5432/excel_chat"

    # ── JWT ──
    jwt_secret: str = "change_this_to_a_random_secret_key"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # ── Admin default ──
    default_admin_user: str = "admin"
    default_admin_pass: str = "admin123"

    # ── Limits ──
    max_file_size_mb: int = 10
    max_rows: int = 100_000
    query_timeout_seconds: int = 30

    # ── Sessions ──
    session_ttl_minutes: int = 60          # Expire sessions after N minutes of inactivity
    max_sessions: int = 50                 # Maximum concurrent sessions in memory

    # ── Rate Limiting ──
    rate_limit_query: str = "10/minute"    # Queries per user per minute
    rate_limit_upload: str = "5/minute"    # Uploads per user per minute
    rate_limit_auth: str = "10/minute"     # Auth attempts per IP per minute

    # ── CORS ──
    cors_origins: list[str] = ["*"]        # ["https://tu-app.onrender.com"] in production

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

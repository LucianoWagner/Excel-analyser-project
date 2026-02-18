from langchain_groq import ChatGroq
from config import settings

_llm_instance = None


def get_llm() -> ChatGroq:
    """Return a singleton ChatGroq instance."""
    global _llm_instance
    if _llm_instance is None:
        if not settings.groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY no configurada. Agregala al archivo .env\n"
                "Obtenerla gratis en: https://console.groq.com"
            )
        _llm_instance = ChatGroq(
            model=settings.groq_model,
            temperature=0,
            api_key=settings.groq_api_key,
        )
    return _llm_instance

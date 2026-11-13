"""Routes package — aggregate all routers."""
from app.api.routes.health import router as health_router
from app.api.routes.ipa import router as ipa_router
from app.api.routes.model_info import router as model_info_router
from app.api.routes.pronunciation import router as pronunciation_router
from app.api.routes.pronunciation_v2 import router as pronunciation_v2_router
from app.api.routes.transcribe import router as transcribe_router

__all__ = [
    "health_router",
    "ipa_router",
    "model_info_router",
    "pronunciation_router",
    "pronunciation_v2_router",
    "transcribe_router",
]

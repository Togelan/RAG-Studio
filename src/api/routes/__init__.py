# src/api/routes — FastAPI route modules

from src.api.routes.chat import router as chat_router
from src.api.routes.ui import router as ui_router

__all__ = ["chat_router", "ui_router"]

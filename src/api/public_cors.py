"""CORS middleware partition between authenticated APIs and public widgets."""

from __future__ import annotations

from typing import Final

from fastapi.middleware.cors import CORSMiddleware
from starlette.types import Receive, Scope, Send

_PUBLIC_WIDGET_PREFIX: Final = "/api/public/widgets/"


class PartitionedCORSMiddleware(CORSMiddleware):
    """Leave publication-specific public CORS to its exact-origin route."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] == "http" and path.startswith(_PUBLIC_WIDGET_PREFIX):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

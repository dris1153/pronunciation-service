"""Global exception handlers and CORS middleware."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.config import get_settings


def register_middleware(app: FastAPI) -> None:
    """Attach CORS and custom exception handlers."""

    settings = get_settings()
    origins = settings.cors_origins

    # CORS spec forbids Access-Control-Allow-Credentials: true together with
    # Access-Control-Allow-Origin: *.  Only enable credentials when specific
    # origins are configured.
    is_wildcard = origins == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=not is_wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on {} {}", request.method, request.url)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error.", "error_code": "INTERNAL"},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "error_code": "VALIDATION"},
        )

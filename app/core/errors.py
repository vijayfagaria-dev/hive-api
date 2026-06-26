"""Centralized error handling.

Services raise *semantic* domain errors (they know nothing about HTTP). A single
exception handler maps each to the right status code and the standard
`{"detail": ...}` body — so routes never repeat `try/except -> HTTPException`.

Status mapping is chosen to preserve the existing API contract exactly:
  DomainError 400 · Unauthorized 401 · Forbidden 403 · NotFound 404 ·
  Conflict 409 · PayloadTooLarge 413 · UnsupportedMedia 415 · Unprocessable 422
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base application error. `status_code` decides the HTTP response."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class DomainError(AppError):
    """A business-rule or invalid-state violation (e.g. 'only the accused can
    accept'). The workhorse error services raise. Maps to 400."""

    status_code = 400


class Unauthorized(AppError):
    status_code = 401


class Forbidden(AppError):
    status_code = 403


class NotFound(AppError):
    status_code = 404


class Conflict(AppError):
    status_code = 409


class PayloadTooLarge(AppError):
    status_code = 413


class UnsupportedMedia(AppError):
    status_code = 415


class Unprocessable(AppError):
    status_code = 422


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

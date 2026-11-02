"""Centralized error handling.

Services raise *semantic* domain errors (they know nothing about HTTP). A single
exception handler maps each to the right status code and the standard
`{"detail": ...}` body — so routes never repeat `try/except -> HTTPException`.

Status mapping is chosen to preserve the existing API contract exactly:
  DomainError 400 · Unauthorized 401 · Forbidden 403 · NotFound 404 ·
  Conflict 409 · PayloadTooLarge 413 · UnsupportedMedia 415 · Unprocessable 422 ·
  TooManyRequests 429

An error normally rolls the request's transaction back. `persist=True` keeps the
writes made before the raise — for security counters (failed logins, wrong OTP
guesses) that must stick precisely because the request failed.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base application error. `status_code` decides the HTTP response."""

    status_code: int = 400

    def __init__(self, detail: str, *, persist: bool = False) -> None:
        super().__init__(detail)
        self.detail = detail
        self.persist = persist


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


class TooManyRequests(AppError):
    """Throttled (rate limit, lockout, OTP cooldown). `retry_after` -> Retry-After header."""

    status_code = 429

    def __init__(self, detail: str, *, retry_after: Optional[int] = None, persist: bool = False) -> None:
        super().__init__(detail, persist=persist)
        self.retry_after = retry_after


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = None
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            headers = {"Retry-After": str(max(1, int(retry_after)))}
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)

"""HTTP-слой входа: почта (magic link), код из Telegram-бота, сессия в cookie."""

from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ..db import get_db, init_db
from ..services import users

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

COOKIE_MAX_AGE = 60 * 60 * 24 * 30


class EmailIn(BaseModel):
    email: str = Field(..., examples=["operator@example.com"])


class CodeIn(BaseModel):
    code: str = Field(..., examples=["123456"])


def _base_url(request: Request) -> str:
    # За прокси Render/nginx схема приходит в X-Forwarded-Proto.
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _is_local(request: Request) -> bool:
    """Dev-ссылка допустима только на локальном хосте — иначе это вход без пароля."""
    host = (request.headers.get("host") or request.url.netloc or "").split(":")[0].lower()
    return host in {"localhost", "127.0.0.1", "testserver", "0.0.0.0"}


def _set_session(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        users.SESSION_COOKIE,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
        path="/",
    )


def current_user(request: Request, conn: sqlite3.Connection) -> sqlite3.Row | None:
    return users.user_by_session(conn, request.cookies.get(users.SESSION_COOKIE))


@router.post("/email/request", summary="Запросить ссылку для входа на почту")
def request_email(payload: EmailIn, request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    init_db()
    users.ensure_schema(conn)
    try:
        result = users.issue_email_code(conn, payload.email, _base_url(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conn.commit()
    # На публичном хосте без SMTP вход по почте выключен: иначе любой, кто знает
    # адрес, получил бы ссылку и вошёл. Остаётся Telegram-бот.
    if result["delivery"] == "dev" and not _is_local(request) and os.environ.get("ALLOW_DEV_LOGIN") != "1":
        result["dev_link"] = None
        result["delivery"] = "disabled"
        result["message"] = "Почта не настроена. Используйте вход через Telegram-бота."
    return result


@router.get("/email/confirm", summary="Подтвердить вход по ссылке из письма")
def confirm_email(token: str, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    users.ensure_schema(conn)
    session = users.confirm_email_code(conn, token)
    if not session:
        raise HTTPException(status_code=400, detail="Ссылка недействительна или истекла")
    conn.commit()
    response = RedirectResponse("/account?signed=1", status_code=303)
    _set_session(response, session, request)
    return response


@router.post("/telegram/claim", summary="Войти по коду из Telegram-бота")
def claim_telegram(payload: CodeIn, request: Request, response: Response,
                   conn: sqlite3.Connection = Depends(get_db)) -> dict:
    users.ensure_schema(conn)
    session = users.confirm_telegram_code(conn, payload.code)
    if not session:
        raise HTTPException(status_code=400, detail="Код неверный или истёк")
    conn.commit()
    _set_session(response, session, request)
    user = users.user_by_session(conn, session)
    return {"status": "ok", "user": users.user_public(user)}


@router.get("/me", summary="Текущий пользователь и тариф")
def me(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    users.ensure_schema(conn)
    user = current_user(request, conn)
    if not user:
        return {"authenticated": False, "ads": True, "plan": None}
    return {"authenticated": True, **users.user_public(user)}


@router.post("/logout", summary="Выйти")
def logout(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    token = request.cookies.get(users.SESSION_COOKIE)
    if token:
        users.ensure_schema(conn)
        users.drop_session(conn, token)
        conn.commit()
    response.delete_cookie(users.SESSION_COOKIE, path="/")
    return {"status": "ok"}

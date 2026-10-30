"""HTTP-слой авторизации сотрудников.

Сессия — HttpOnly-cookie `sid`. Регистрация и вход — по почте и паролю.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..db import get_db
from ..services import auth, mailer

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "sid"


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class EmailStartIn(BaseModel):
    email: str
    full_name: str | None = None
    next: str | None = None


class EmailCodeIn(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=6)


class EmailOnlyIn(BaseModel):
    email: str


def current_employee(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict | None:
    return auth.employee_by_session(conn, request.cookies.get(COOKIE))


def require_employee(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    employee = auth.employee_by_session(conn, request.cookies.get(COOKIE))
    if not employee:
        raise HTTPException(status_code=401, detail="Нужно войти в систему")
    return employee


def require_admin(employee: dict = Depends(require_employee)) -> dict:
    """Аналитика и выгрузки — только администратору."""
    if employee.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Аналитика доступна только администратору")
    return employee


def _set_session(response: Response, conn: sqlite3.Connection, employee: dict) -> None:
    token, _expires = auth.create_session(conn, employee["id"])
    response.set_cookie(
        COOKIE,
        token,
        max_age=auth.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        path="/",
    )


@router.post("/register", summary="Регистрация по почте с подтверждением")
def register(payload: RegisterIn, conn: sqlite3.Connection = Depends(get_db)):
    """Создаёт сотрудника и отправляет письмо. Сессию не выдаём до подтверждения."""
    try:
        employee = auth.register(conn, payload.email, payload.password, payload.full_name)
        token, _code = auth.issue_confirmation(conn, employee)
    except auth.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)

    link = f"{settings.public_base_url.rstrip('/')}/auth/email/confirm?token={token}"
    sent = mailer.send_confirm_link(employee["email"], link, auth.CONFIRM_MINUTES // 60)
    response = {
        "employee": auth.public_employee(employee),
        "needs_confirmation": True,
        "email_status": sent.status,
        "email_detail": sent.detail,
        "expires_in_hours": auth.CONFIRM_MINUTES // 60,
    }
    if sent.status == "file":
        response["dev_link"] = link
    return response


@router.get("/email/confirm", summary="Подтверждение почты по ссылке", include_in_schema=False)
def email_confirm(token: str = Query(default=""), conn: sqlite3.Connection = Depends(get_db)):
    try:
        employee = auth.confirm_by_token(conn, token)
    except auth.AuthError as exc:
        return RedirectResponse(f"/login?error={exc.status}&next=/", status_code=303)
    response = RedirectResponse("/?confirmed=1", status_code=303)
    _set_session(response, conn, employee)
    return response


@router.post("/email/resend-confirm", summary="Отправить письмо подтверждения ещё раз")
def resend_confirm(payload: EmailOnlyIn, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Ответ всегда нейтральный: не раскрываем, есть ли такой аккаунт."""
    try:
        employee = auth.employee_by_email(conn, auth.normalize_email(payload.email))
    except auth.AuthError:
        employee = None
    result = {"ok": True}
    if employee and employee["is_active"] and not employee.get("email_confirmed_at"):
        try:
            token, _code = auth.issue_confirmation(conn, employee)
        except auth.AuthError:
            return result
        link = f"{settings.public_base_url.rstrip('/')}/auth/email/confirm?token={token}"
        sent = mailer.send_confirm_link(employee["email"], link, auth.CONFIRM_MINUTES // 60)
        result["email_status"] = sent.status
        if sent.status == "file":
            result["dev_link"] = link
    return result


@router.post("/login", summary="Вход по email и паролю")
def login(payload: LoginIn, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    try:
        employee = auth.login(conn, payload.email, payload.password)
    except auth.AuthError as exc:
        detail = exc.message
        if exc.status == 403:
            detail = "Почта не подтверждена: откройте ссылку из письма или запросите новое."
        raise HTTPException(status_code=exc.status, detail=detail)
    _set_session(response, conn, employee)
    return {"employee": auth.public_employee(employee)}


@router.post("/logout", summary="Выход")
def logout(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    auth.delete_session(conn, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/email/start", summary="Отправить ссылку и код для входа на почту")
def email_start(payload: EmailStartIn, conn: sqlite3.Connection = Depends(get_db)):
    """Пароль не нужен: нового сотрудника заводим сразу по почте."""
    try:
        result = auth.start_email_login(conn, payload.email, payload.full_name)
    except auth.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)

    link = f"{settings.public_base_url.rstrip('/')}/auth/email/verify?token={result['token']}"
    sent = mailer.send_login_link(
        result["email"], link, result["code"], result["expires_in_minutes"]
    )
    response = {
        "ok": sent.status in ("sent", "file"),
        "email": result["email"],
        "expires_in_minutes": result["expires_in_minutes"],
        "email_status": sent.status,
        "email_detail": sent.detail,
        "created": result["created"],
        "employee": auth.public_employee(result["employee"]),
    }
    if sent.status == "disabled":
        raise HTTPException(
            status_code=503,
            detail="Отправка почты выключена: задайте SMTP_* или EMAIL_TRANSPORT=file",
        )
    # Демо-режим без SMTP: отдаём ссылку сразу, чтобы не лезть в файл руками.
    if sent.status == "file":
        response["dev_link"] = link
        response["dev_code"] = result["code"]
    return response


@router.get("/email/verify", summary="Вход по ссылке из письма", include_in_schema=False)
def email_verify(token: str = Query(default=""), conn: sqlite3.Connection = Depends(get_db)):
    """Открывается из письма: ставит сессию и ведёт в панель."""
    try:
        employee = auth.login_by_token(conn, token)
    except auth.AuthError as exc:
        return RedirectResponse(f"/login?error={exc.status}&next=/", status_code=303)
    response = RedirectResponse("/", status_code=303)
    _set_session(response, conn, employee)
    return response


@router.post("/email/verify", summary="Вход по коду из письма")
def email_code_login(
    payload: EmailCodeIn,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
):
    try:
        employee = auth.login_by_email_code(conn, payload.email, payload.code)
    except auth.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    _set_session(response, conn, employee)
    return {"employee": auth.public_employee(employee)}


@router.get("/me", summary="Текущий сотрудник")
def me(employee: dict | None = Depends(current_employee)):
    return {"employee": auth.public_employee(employee)}


@router.post("/password", summary="Смена пароля")
def change_password(
    payload: PasswordIn,
    response: Response,
    employee: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    try:
        auth.change_password(conn, employee, payload.current_password, payload.new_password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    _set_session(response, conn, employee)
    return {"ok": True}

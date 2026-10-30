"""HTTP-слой внутреннего мессенджера.

Все маршруты требуют активной сессии сотрудника: чат — часть рабочего места,
а не публичная страница.
"""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..db import get_db
from ..services import chat
from .auth import require_employee

router = APIRouter(prefix="/chat", tags=["chat"])


class ConversationIn(BaseModel):
    kind: Literal["direct", "group"] = "direct"
    title: str = ""
    employee_ids: list[int] = Field(default_factory=list)


class ConversationUpdateIn(BaseModel):
    title: str | None = None
    topic: str | None = None


class MembersIn(BaseModel):
    employee_ids: list[int] = Field(default_factory=list)


class MessageIn(BaseModel):
    body: str = ""
    reply_to: int | None = None
    mentions: list[int] = Field(default_factory=list)


class MuteIn(BaseModel):
    muted: bool = True


class ReadIn(BaseModel):
    message_id: int = 0


@router.get("/bootstrap", summary="Справочники и список диалогов")
def bootstrap(
    me: dict = Depends(require_employee), conn: sqlite3.Connection = Depends(get_db)
):
    return chat.bootstrap(conn, me)


@router.get("/summary", summary="Счётчик непрочитанных для главной")
def summary(
    me: dict = Depends(require_employee), conn: sqlite3.Connection = Depends(get_db)
):
    return chat.unread_summary(conn, me)


@router.post("/conversations", summary="Создать личный диалог или группу")
def create_conversation(
    payload: ConversationIn,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"conversation": chat.create_conversation(
        conn, me, payload.kind, payload.title, payload.employee_ids
    )}


@router.get("/conversations/{channel_id}", summary="Диалог и участники")
def conversation(
    channel_id: int,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return chat.conversation_details(conn, channel_id, me)


@router.patch("/conversations/{channel_id}", summary="Название и тема группы")
def update_conversation(
    channel_id: int,
    payload: ConversationUpdateIn,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return chat.update_conversation(conn, channel_id, me, payload.title, payload.topic)


@router.post("/conversations/{channel_id}/members", summary="Добавить участников")
def add_members(
    channel_id: int,
    payload: MembersIn,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return chat.add_members(conn, channel_id, me, payload.employee_ids)


@router.delete("/conversations/{channel_id}/members/{employee_id}", summary="Удалить участника")
def remove_member(
    channel_id: int,
    employee_id: int,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return chat.remove_member(conn, channel_id, me, employee_id)


@router.post("/conversations/{channel_id}/leave", summary="Выйти из группы")
def leave_conversation(
    channel_id: int,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return chat.leave_conversation(conn, channel_id, me)


@router.post("/conversations/{channel_id}/mute", summary="Выключить уведомления")
def mute_conversation(
    channel_id: int,
    payload: MuteIn,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"conversation": chat.set_muted(conn, channel_id, me, payload.muted)}


@router.get("/conversations/{channel_id}/messages", summary="Лента сообщений")
def messages(
    channel_id: int,
    after_id: int = Query(default=0, ge=0),
    before_id: int = Query(default=0, ge=0),
    around_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    q: str = Query(default="", max_length=200),
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return chat.list_messages(
        conn,
        channel_id,
        me,
        after_id=after_id,
        before_id=before_id,
        around_id=around_id,
        limit=limit,
        query=q,
    )


@router.post("/conversations/{channel_id}/messages", summary="Отправить сообщение")
def send_message(
    channel_id: int,
    payload: MessageIn,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"message": chat.send_message(
        conn, channel_id, me, payload.body, payload.reply_to, payload.mentions
    )}


@router.post("/conversations/{channel_id}/attachments", summary="Отправить файл")
async def upload_attachment(
    channel_id: int,
    request: Request,
    filename: str = Query(default="файл", max_length=200),
    caption: str = Query(default="", max_length=4000),
    reply_to: int | None = Query(default=None),
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    max_bytes = settings.chat_max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status_code=413, detail=f"Файл больше {settings.chat_max_upload_mb} МБ"
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    message = chat.save_attachment(
        conn,
        channel_id,
        me,
        filename=filename,
        mime=request.headers.get("content-type", ""),
        data=data,
        caption=caption,
        reply_to=reply_to,
    )
    return {"message": message}


@router.patch("/messages/{message_id}", summary="Изменить сообщение")
def edit_message(
    message_id: int,
    payload: MessageIn,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"message": chat.edit_message(conn, message_id, me, payload.body)}


@router.delete("/messages/{message_id}", summary="Удалить сообщение")
def delete_message(
    message_id: int,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return chat.delete_message(conn, message_id, me)


@router.post("/conversations/{channel_id}/read", summary="Отметить прочитанным")
def mark_read(
    channel_id: int,
    payload: ReadIn,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return chat.mark_read(conn, channel_id, me, payload.message_id)


@router.post("/conversations/{channel_id}/typing", summary="Печатает…")
def set_typing(
    channel_id: int,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return chat.set_typing(conn, channel_id, me)


@router.get("/search", summary="Поиск по сообщениям")
def search(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=30, ge=1, le=60),
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"results": chat.search_messages(conn, me, q, limit)}


@router.get("/attachments/{attachment_id}", summary="Скачать вложение", include_in_schema=False)
def download_attachment(
    attachment_id: int,
    me: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
):
    info = chat.attachment_for_download(conn, attachment_id, me)
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=600"}
    if info["inline"]:
        headers["Content-Disposition"] = "inline"
        return FileResponse(info["path"], media_type=info["mime"], headers=headers)
    return FileResponse(
        info["path"],
        media_type="application/octet-stream",
        filename=info["filename"],
        headers=headers,
    )

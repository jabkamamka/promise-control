"""HTTP-слой: типы обещаний (встроенные и пользовательские)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db
from ..schemas import PromiseTypeIn, PromiseTypeOut
from ..services.tasks import TaskError, create_type, delete_type, list_types

router = APIRouter(prefix="/api/v1/promise-types", tags=["promise-types"])


@router.get("", response_model=list[PromiseTypeOut], summary="Справочник типов обещаний")
def types_list(conn: sqlite3.Connection = Depends(get_db)) -> list[PromiseTypeOut]:
    return [PromiseTypeOut(**t) for t in list_types(conn)]


@router.post("", response_model=PromiseTypeOut, status_code=201, summary="Добавить свой тип обещания")
def types_create(payload: PromiseTypeIn, conn: sqlite3.Connection = Depends(get_db)) -> PromiseTypeOut:
    try:
        created = create_type(conn, payload.model_dump())
    except TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return PromiseTypeOut(**created)


@router.delete("/{code}", status_code=204, summary="Удалить пользовательский тип")
def types_delete(code: str, conn: sqlite3.Connection = Depends(get_db)) -> None:
    try:
        delete_type(conn, code)
    except KeyError:
        raise HTTPException(status_code=404, detail="Тип не найден")
    except TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

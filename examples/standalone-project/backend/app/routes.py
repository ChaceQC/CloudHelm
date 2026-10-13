from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import NoteRecord
from app.schemas import NoteCreate, NotePatch, NoteRead, SafeError


router = APIRouter(
    prefix="/api/notes",
    tags=["notes"],
    responses={503: {"model": SafeError}},
)
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[NoteRead])
def list_notes(session: DatabaseSession) -> list[NoteRecord]:
    statement = select(NoteRecord).order_by(NoteRecord.id.asc())
    return list(session.scalars(statement).all())


@router.post(
    "",
    response_model=NoteRead,
    status_code=201,
    responses={422: {"model": SafeError}},
)
def create_note(payload: NoteCreate, session: DatabaseSession) -> NoteRecord:
    note = NoteRecord(title=payload.title, body=payload.body)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


@router.get(
    "/{note_id}",
    response_model=NoteRead,
    responses={422: {"model": SafeError}},
)
def get_note(
    note_id: Annotated[int, Path(gt=0)], session: DatabaseSession
) -> NoteRecord:
    note = session.get(NoteRecord, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    return note


@router.patch(
    "/{note_id}",
    response_model=NoteRead,
    responses={422: {"model": SafeError}},
)
def update_note(
    payload: NotePatch,
    note_id: Annotated[int, Path(gt=0)],
    session: DatabaseSession,
) -> NoteRecord:
    note = session.get(NoteRecord, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")

    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(note, name, value)
    session.commit()
    session.refresh(note)
    return note


@router.delete(
    "/{note_id}",
    status_code=204,
    responses={422: {"model": SafeError}},
)
def delete_note(
    note_id: Annotated[int, Path(gt=0)], session: DatabaseSession
) -> Response:
    note = session.get(NoteRecord, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    session.delete(note)
    session.commit()
    return Response(status_code=204)

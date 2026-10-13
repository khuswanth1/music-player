import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser
from app.realtime.hub import hub
from app.schemas.common import Message
from app.services import sessions as svc

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSession(BaseModel):
    name: str = Field(default="", max_length=120)


class JoinSession(BaseModel):
    invite_code: str = Field(min_length=4, max_length=32)


class ControlRequest(BaseModel):
    action: svc.ControlAction
    song_id: uuid.UUID | None = None
    position_ms: int | None = Field(default=None, ge=0)
    index: int | None = Field(default=None, ge=0)


def broadcast_state(db, session) -> None:
    state = svc.serialize(db, session, None).model_dump(mode="json", exclude={"is_host"})
    hub.publish(f"session:{session.id}", {"type": "session.state", "session": state})


@router.post("", response_model=svc.SessionOut, status_code=201, summary="Start a group session (Premium)")
def create_session(data: CreateSession, user: CurrentUser, db: DB):
    return svc.serialize(db, svc.create(db, user, data.name), user)


@router.get("/active", response_model=list[svc.SessionOut])
def active_sessions(user: CurrentUser, db: DB):
    return [svc.serialize(db, s, user) for s in svc.list_active(db, user)]


@router.post("/join", response_model=svc.SessionOut)
def join_session(data: JoinSession, user: CurrentUser, db: DB):
    session = svc.join(db, user, data.invite_code)
    broadcast_state(db, session)
    return svc.serialize(db, session, user)


@router.get("/{session_id}", response_model=svc.SessionOut)
def get_session(session_id: uuid.UUID, user: CurrentUser, db: DB):
    return svc.serialize(db, svc.get_for_participant(db, session_id, user), user)


@router.post("/{session_id}/control", response_model=svc.SessionOut,
             summary="Change playback or the shared queue (also available over the WebSocket)")
def control(session_id: uuid.UUID, data: ControlRequest, user: CurrentUser, db: DB):
    session = svc.apply_control(db, user, session_id, data.action, song_id=str(data.song_id) if data.song_id else None,
                                position_ms=data.position_ms, index=data.index)
    broadcast_state(db, session)
    return svc.serialize(db, session, user)


@router.post("/{session_id}/leave", response_model=Message)
def leave_session(session_id: uuid.UUID, user: CurrentUser, db: DB):
    session = svc.leave(db, user, session_id)
    broadcast_state(db, session)
    return Message(message="Left session")


@router.delete("/{session_id}", response_model=Message)
def end_session(session_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.end(db, user, session_id)
    hub.publish(f"session:{session_id}", {"type": "session.ended", "session_id": str(session_id)})
    return Message(message="Session ended")

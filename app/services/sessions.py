"""Group listening sessions: one host drives playback, members follow along and add to a shared queue."""

import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, Forbidden, NotFound
from app.core.security import generate_invite_code, utcnow
from app.models import PlaybackSession, PlaybackSessionMember, Song, User
from app.schemas.catalog import SongOut
from app.schemas.user import UserPublic
from app.services import catalog as catalog_svc
from app.services.entitlements import require_premium

MAX_QUEUE = 200


class SessionOut(BaseModel):
    id: uuid.UUID
    name: str
    invite_code: str
    is_active: bool
    is_host: bool
    host: UserPublic
    members: list[UserPublic]
    current_song: SongOut | None
    position_ms: int
    is_playing: bool
    queue: list[SongOut]
    state_updated_at: str
    server_time: str


def _members(db: Session, session_id: uuid.UUID) -> list[PlaybackSessionMember]:
    return list(db.scalars(select(PlaybackSessionMember).where(PlaybackSessionMember.session_id == session_id)
                           .order_by(PlaybackSessionMember.created_at)).unique())


def is_participant(db: Session, session: PlaybackSession, user_id: uuid.UUID) -> bool:
    return session.host_id == user_id or db.get(PlaybackSessionMember, (session.id, user_id)) is not None


def serialize(db: Session, session: PlaybackSession, user: User | None) -> SessionOut:
    """`user=None` gives a viewer-neutral payload for broadcasts (no per-user `liked` flags)."""
    queue_ids = [uuid.UUID(i) for i in session.queue]
    songs = {s.id: s for s in db.scalars(select(Song).where(Song.id.in_(queue_ids))).unique()} if queue_ids else {}
    ordered = [songs[i] for i in queue_ids if i in songs]
    current = [session.current_song] if session.current_song else []
    outs = catalog_svc.song_outs(db, user, current + ordered)
    return SessionOut(
        id=session.id, name=session.name, invite_code=session.invite_code, is_active=session.is_active,
        is_host=user is not None and session.host_id == user.id, host=UserPublic.model_validate(session.host),
        members=[UserPublic.model_validate(m.user) for m in _members(db, session.id)],
        current_song=outs[0] if current else None, position_ms=session.position_ms,
        is_playing=session.is_playing, queue=outs[1:] if current else outs,
        state_updated_at=session.state_updated_at.isoformat(), server_time=utcnow().isoformat(),
    )


def get_for_participant(db: Session, session_id: uuid.UUID, user: User) -> PlaybackSession:
    session = db.get(PlaybackSession, session_id)
    if session is None or not is_participant(db, session, user.id):
        raise NotFound("Session not found")
    return session


def create(db: Session, user: User, name: str) -> PlaybackSession:
    require_premium(db, user, "Hosting a group session")
    # One live session per host: starting a new one ends the old.
    db.execute(update(PlaybackSession).where(PlaybackSession.host_id == user.id, PlaybackSession.is_active.is_(True))
               .values(is_active=False, is_playing=False, ended_at=utcnow()))
    session = PlaybackSession(host_id=user.id, name=name.strip() or f"{user.display_name}'s session",
                              invite_code=generate_invite_code(), queue=[], position_ms=0, is_playing=False)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_active(db: Session, user: User) -> list[PlaybackSession]:
    member_of = select(PlaybackSessionMember.session_id).where(PlaybackSessionMember.user_id == user.id)
    return list(db.scalars(select(PlaybackSession).where(
        PlaybackSession.is_active.is_(True),
        (PlaybackSession.host_id == user.id) | PlaybackSession.id.in_(member_of))
        .order_by(PlaybackSession.created_at.desc())).unique())


def join(db: Session, user: User, invite_code: str) -> PlaybackSession:
    session = db.scalar(select(PlaybackSession).where(PlaybackSession.invite_code == invite_code,
                                                      PlaybackSession.is_active.is_(True)))
    if session is None:
        raise NotFound("This session has ended or the code is wrong")
    if not is_participant(db, session, user.id):
        db.add(PlaybackSessionMember(session_id=session.id, user_id=user.id))
        db.commit()
    return session


def leave(db: Session, user: User, session_id: uuid.UUID) -> PlaybackSession:
    session = get_for_participant(db, session_id, user)
    if session.host_id == user.id:
        raise AppError("Hosts end the session instead of leaving it", code="host_cannot_leave")
    member = db.get(PlaybackSessionMember, (session.id, user.id))
    if member:
        db.delete(member)
        db.commit()
    return session


def end(db: Session, user: User, session_id: uuid.UUID) -> PlaybackSession:
    session = get_for_participant(db, session_id, user)
    if session.host_id != user.id:
        raise Forbidden("Only the host can end the session")
    session.is_active, session.is_playing, session.ended_at = False, False, utcnow()
    db.commit()
    return session


ControlAction = Literal["play", "pause", "seek", "play_song", "next", "prev", "queue_add", "queue_remove"]


def apply_control(db: Session, user: User, session_id: uuid.UUID, action: str, *,
                  song_id: str | None = None, position_ms: int | None = None, index: int | None = None) -> PlaybackSession:
    """Mutates session state. Host controls playback; any participant can add to the queue."""
    session = db.scalar(select(PlaybackSession).where(PlaybackSession.id == session_id)
                        .with_for_update(of=PlaybackSession))
    if session is None or not is_participant(db, session, user.id):
        raise NotFound("Session not found")
    if not session.is_active:
        raise AppError("This session has ended", code="session_ended")
    is_host = session.host_id == user.id
    if action != "queue_add" and not is_host:
        raise Forbidden("Only the host controls playback")

    now = utcnow()
    if session.is_playing:  # bank the elapsed time before changing state
        elapsed = int((now - session.state_updated_at).total_seconds() * 1000)
        session.position_ms = session.position_ms + max(0, elapsed)

    def _song(sid: str | None) -> Song:
        try:
            return catalog_svc.get_song(db, uuid.UUID(str(sid)), user)
        except ValueError as exc:
            raise NotFound("Song not found") from exc

    match action:
        case "play":
            if session.current_song_id is None:
                raise AppError("Pick a song first", code="nothing_to_play")
            session.is_playing = True
        case "pause":
            session.is_playing = False
        case "seek":
            session.position_ms = max(0, int(position_ms or 0))
        case "play_song":
            session.current_song_id = _song(song_id).id
            session.position_ms, session.is_playing = 0, True
        case "next":
            queue = list(session.queue)
            if queue:
                session.current_song_id = uuid.UUID(queue.pop(0))
                session.queue, session.position_ms, session.is_playing = queue, 0, True
            else:
                session.is_playing, session.position_ms = False, 0
        case "prev":
            session.position_ms = 0
        case "queue_add":
            if len(session.queue) >= MAX_QUEUE:
                raise AppError("The queue is full", code="queue_full")
            session.queue = [*session.queue, str(_song(song_id).id)]
        case "queue_remove":
            queue = list(session.queue)
            if index is None or not 0 <= index < len(queue):
                raise AppError("Invalid queue index", code="validation_error")
            queue.pop(index)
            session.queue = queue
        case _:
            raise AppError("Unknown action", code="validation_error")
    if session.current_song and session.position_ms > session.current_song.duration_ms:
        session.position_ms = session.current_song.duration_ms
    session.state_updated_at = now
    db.commit()
    db.refresh(session)
    return session

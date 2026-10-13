import uuid
from collections.abc import Sequence

from fastapi import UploadFile
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, Forbidden, NotFound, PaymentRequired
from app.core.permissions import Perm, has_permission
from app.core.security import generate_invite_code, utcnow
from app.models import Playlist, PlaylistCollaborator, PlaylistTrack, SavedPlaylist, Song, User
from app.realtime.hub import hub
from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistDetail,
    PlaylistSummary,
    PlaylistTrackOut,
    PlaylistUpdate,
)
from app.schemas.user import UserPublic
from app.services import catalog as catalog_svc
from app.services.entitlements import is_premium, playlist_limit, require_premium

MAX_TRACKS = 10_000


# --- access rules --------------------------------------------------------------------------

def _is_collaborator(db: Session, playlist: Playlist, user: User) -> bool:
    return db.get(PlaylistCollaborator, (playlist.id, user.id)) is not None


def can_view(db: Session, playlist: Playlist, user: User | None) -> bool:
    if playlist.is_public:
        return True
    if user is None:
        return False
    return (playlist.owner_id == user.id or _is_collaborator(db, playlist, user)
            or has_permission(user.role_name, Perm.playlists_moderate))


def can_edit(db: Session, playlist: Playlist, user: User | None) -> bool:
    if user is None:
        return False
    if playlist.owner_id == user.id:
        return True
    return playlist.is_collaborative and _is_collaborator(db, playlist, user)


def get_viewable(db: Session, playlist_id: uuid.UUID, user: User | None) -> Playlist:
    playlist = db.get(Playlist, playlist_id)
    # Private playlists 404 rather than 403 so their existence isn't revealed.
    if playlist is None or not can_view(db, playlist, user):
        raise NotFound("Playlist not found")
    return playlist


def _lock_for_edit(db: Session, playlist_id: uuid.UUID, user: User) -> Playlist:
    """Row lock serialises concurrent edits so positions stay consistent."""
    playlist = db.scalar(select(Playlist).where(Playlist.id == playlist_id).with_for_update(of=Playlist))
    if playlist is None or not can_view(db, playlist, user):
        raise NotFound("Playlist not found")
    if not can_edit(db, playlist, user):
        raise Forbidden("You can't edit this playlist")
    return playlist


def _lock_for_owner(db: Session, playlist_id: uuid.UUID, user: User, *, allow_moderator: bool = False) -> Playlist:
    playlist = db.scalar(select(Playlist).where(Playlist.id == playlist_id).with_for_update(of=Playlist))
    if playlist is None or not can_view(db, playlist, user):
        raise NotFound("Playlist not found")
    moderator = allow_moderator and has_permission(user.role_name, Perm.playlists_moderate)
    if playlist.owner_id != user.id and not moderator:
        raise Forbidden("Only the owner can do that")
    return playlist


def _notify(playlist: Playlist, action: str, user: User) -> None:
    hub.publish(f"playlist:{playlist.id}", {
        "type": "playlist.updated", "playlist_id": str(playlist.id), "action": action,
        "by": {"user_id": str(user.id), "display_name": user.display_name},
    })


# --- serialization -------------------------------------------------------------------------

def _track_counts(db: Session, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = db.execute(select(PlaylistTrack.playlist_id, func.count()).where(PlaylistTrack.playlist_id.in_(ids))
                      .group_by(PlaylistTrack.playlist_id)).all()
    return {pid: count for pid, count in rows}


def summarize_many(db: Session, playlists: list[Playlist]) -> list[PlaylistSummary]:
    counts = _track_counts(db, [p.id for p in playlists])
    return [PlaylistSummary(id=p.id, name=p.name, description=p.description, cover_url=p.cover_url,
                            is_public=p.is_public, is_collaborative=p.is_collaborative,
                            owner=UserPublic.model_validate(p.owner), track_count=counts.get(p.id, 0),
                            updated_at=p.updated_at) for p in playlists]


def detail(db: Session, playlist: Playlist, user: User | None) -> PlaylistDetail:
    items = db.scalars(select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist.id)
                       .order_by(PlaylistTrack.position)).unique().all()
    songs = catalog_svc.song_outs(db, user, [i.song for i in items])
    tracks = [PlaylistTrackOut(id=i.id, position=i.position, added_at=i.added_at,
                               added_by=UserPublic.model_validate(i.added_by) if i.added_by else None, song=s)
              for i, s in zip(items, songs, strict=True)]
    collaborators = db.scalars(select(PlaylistCollaborator).where(PlaylistCollaborator.playlist_id == playlist.id)
                               .order_by(PlaylistCollaborator.created_at)).unique().all()
    is_owner = user is not None and playlist.owner_id == user.id
    summary = summarize_many(db, [playlist])[0]
    return PlaylistDetail(
        **summary.model_dump(), tracks=tracks, total_duration_ms=sum(t.song.duration_ms for t in tracks),
        collaborators=[UserPublic.model_validate(c.user) for c in collaborators],
        can_edit=can_edit(db, playlist, user), is_owner=is_owner,
        is_saved=(db.get(SavedPlaylist, (user.id, playlist.id)) is not None) if user else None,
        collab_invite_code=playlist.collab_invite_code if is_owner else None,
    )


# --- playlist CRUD -------------------------------------------------------------------------

def list_for_user(db: Session, user: User) -> list[PlaylistSummary]:
    """Playlists the user owns or collaborates on."""
    collab_ids = select(PlaylistCollaborator.playlist_id).where(PlaylistCollaborator.user_id == user.id)
    playlists = db.scalars(select(Playlist).where((Playlist.owner_id == user.id) | Playlist.id.in_(collab_ids))
                           .order_by(Playlist.updated_at.desc())).unique().all()
    return summarize_many(db, list(playlists))


def create(db: Session, user: User, data: PlaylistCreate) -> Playlist:
    limit = playlist_limit(db, user)
    if limit is not None:
        owned = db.scalar(select(func.count()).where(Playlist.owner_id == user.id)) or 0
        if owned >= limit:
            raise PaymentRequired(f"Free accounts can have up to {limit} playlists. Upgrade to Premium for unlimited playlists.",
                                  details={"feature": "unlimited_playlists", "limit": limit})
    if data.is_collaborative:
        require_premium(db, user, "Creating collaborative playlists")
    playlist = Playlist(owner_id=user.id, name=data.name.strip(), description=data.description,
                        is_public=data.is_public and not data.is_collaborative,
                        is_collaborative=data.is_collaborative,
                        collab_invite_code=generate_invite_code() if data.is_collaborative else None)
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    return playlist


def update_playlist(db: Session, playlist_id: uuid.UUID, user: User, data: PlaylistUpdate) -> Playlist:
    playlist = _lock_for_owner(db, playlist_id, user)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name") is not None:
        playlist.name = changes["name"].strip()
    if changes.get("description") is not None:
        playlist.description = changes["description"]
    collaborative = changes.get("is_collaborative", playlist.is_collaborative)
    public = changes.get("is_public", playlist.is_public)
    if collaborative and not playlist.is_collaborative:
        require_premium(db, user, "Creating collaborative playlists")
    if collaborative and public:
        if changes.get("is_public"):
            raise AppError("Collaborative playlists must be private", code="validation_error", status_code=422)
        public = False  # turning collaboration on makes the playlist private
    playlist.is_collaborative = bool(collaborative)
    playlist.is_public = bool(public)
    if playlist.is_collaborative and not playlist.collab_invite_code:
        playlist.collab_invite_code = generate_invite_code()
    if not playlist.is_collaborative:
        playlist.collab_invite_code = None
    db.commit()
    _notify(playlist, "details", user)
    return playlist


def set_cover(db: Session, playlist_id: uuid.UUID, user: User, upload: UploadFile) -> Playlist:
    playlist = _lock_for_owner(db, playlist_id, user)
    playlist.cover_url = catalog_svc._replace_image(playlist.cover_url, upload, "images/playlists")
    db.commit()
    _notify(playlist, "details", user)
    return playlist


def delete_playlist(db: Session, playlist_id: uuid.UUID, user: User) -> None:
    playlist = _lock_for_owner(db, playlist_id, user, allow_moderator=True)
    db.delete(playlist)
    db.commit()
    hub.publish(f"playlist:{playlist_id}", {"type": "playlist.deleted", "playlist_id": str(playlist_id)})


# --- tracks --------------------------------------------------------------------------------

def _count(db: Session, playlist_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).where(PlaylistTrack.playlist_id == playlist_id)) or 0


def add_tracks(db: Session, playlist_id: uuid.UUID, user: User, song_ids: list[uuid.UUID],
               position: int | None) -> Playlist:
    playlist = _lock_for_edit(db, playlist_id, user)
    found = set(db.scalars(select(Song.id).where(Song.id.in_(song_ids), Song.is_published.is_(True))))
    missing = [str(s) for s in song_ids if s not in found]
    if missing:
        raise NotFound("Some songs were not found", details={"song_ids": missing})
    count = _count(db, playlist.id)
    if count + len(song_ids) > MAX_TRACKS:
        raise AppError(f"Playlists can hold at most {MAX_TRACKS} tracks", code="playlist_full")
    insert_at = count if position is None else min(position, count)
    if insert_at < count:
        db.execute(update(PlaylistTrack)
                   .where(PlaylistTrack.playlist_id == playlist.id, PlaylistTrack.position >= insert_at)
                   .values(position=PlaylistTrack.position + len(song_ids)))
    for offset, song_id in enumerate(song_ids):
        db.add(PlaylistTrack(playlist_id=playlist.id, song_id=song_id, position=insert_at + offset,
                             added_by_id=user.id))
    playlist.updated_at = utcnow()
    db.commit()
    _notify(playlist, "tracks_added", user)
    return playlist


def remove_track(db: Session, playlist_id: uuid.UUID, user: User, item_id: int) -> Playlist:
    playlist = _lock_for_edit(db, playlist_id, user)
    item = db.get(PlaylistTrack, item_id)
    if item is None or item.playlist_id != playlist.id:
        raise NotFound("Track is not in this playlist")
    removed_position = item.position
    db.delete(item)
    db.flush()
    db.execute(update(PlaylistTrack)
               .where(PlaylistTrack.playlist_id == playlist.id, PlaylistTrack.position > removed_position)
               .values(position=PlaylistTrack.position - 1))
    playlist.updated_at = utcnow()
    db.commit()
    _notify(playlist, "track_removed", user)
    return playlist


def reorder(db: Session, playlist_id: uuid.UUID, user: User, from_index: int, to_index: int) -> Playlist:
    playlist = _lock_for_edit(db, playlist_id, user)
    count = _count(db, playlist.id)
    if from_index >= count or to_index >= count:
        raise AppError("Position out of range", code="validation_error", status_code=422)
    if from_index == to_index:
        return playlist
    item = db.scalar(select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist.id,
                                                 PlaylistTrack.position == from_index))
    if from_index < to_index:
        db.execute(update(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist.id,
                                               PlaylistTrack.position > from_index,
                                               PlaylistTrack.position <= to_index)
                   .values(position=PlaylistTrack.position - 1))
    else:
        db.execute(update(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist.id,
                                               PlaylistTrack.position >= to_index,
                                               PlaylistTrack.position < from_index)
                   .values(position=PlaylistTrack.position + 1))
    db.execute(update(PlaylistTrack).where(PlaylistTrack.id == item.id).values(position=to_index))
    playlist.updated_at = utcnow()
    db.commit()  # the deferred unique constraint is checked here, after all shifts
    _notify(playlist, "reordered", user)
    return playlist


# --- collaboration -------------------------------------------------------------------------

def regenerate_invite(db: Session, playlist_id: uuid.UUID, user: User) -> Playlist:
    playlist = _lock_for_owner(db, playlist_id, user)
    if not playlist.is_collaborative:
        raise AppError("Make the playlist collaborative first", code="not_collaborative")
    playlist.collab_invite_code = generate_invite_code()
    db.commit()
    return playlist


def join(db: Session, playlist_id: uuid.UUID, user: User, code: str) -> Playlist:
    playlist = db.get(Playlist, playlist_id)
    if (playlist is None or not playlist.is_collaborative or not playlist.collab_invite_code
            or playlist.collab_invite_code != code):
        raise NotFound("This invite link is invalid or has expired")
    if playlist.owner_id != user.id and not _is_collaborator(db, playlist, user):
        db.add(PlaylistCollaborator(playlist_id=playlist.id, user_id=user.id))
        db.commit()
        _notify(playlist, "collaborator_joined", user)
    return playlist


def remove_collaborator(db: Session, playlist_id: uuid.UUID, user: User, collaborator_id: uuid.UUID) -> None:
    playlist = db.get(Playlist, playlist_id)
    if playlist is None or not can_view(db, playlist, user):
        raise NotFound("Playlist not found")
    if user.id not in (playlist.owner_id, collaborator_id):
        raise Forbidden("Only the owner can remove other collaborators")
    db.execute(delete(PlaylistCollaborator).where(PlaylistCollaborator.playlist_id == playlist.id,
                                                  PlaylistCollaborator.user_id == collaborator_id))
    db.commit()
    _notify(playlist, "collaborator_left", user)


def user_is_premium(db: Session, user: User) -> bool:
    return is_premium(db, user)

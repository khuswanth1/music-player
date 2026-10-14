"""User-managed collections of catalog tracks. Private by default; a public album is reachable by its share code.

Only references to catalog songs (which themselves only reference provider tracks) are stored: no audio, and
nothing the user uploads is hosted - so there is no copyrighted audio to clear.
"""

import uuid

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.security import generate_invite_code
from app.models import PrivateAlbum, PrivateAlbumTrack, Song, User
from app.schemas.private_album import (
    AlbumSort,
    PrivateAlbumCreate,
    PrivateAlbumDetail,
    PrivateAlbumSummary,
    PrivateAlbumTrackOut,
    PrivateAlbumUpdate,
)
from app.schemas.user import UserPublic
from app.services import catalog as catalog_svc

MAX_ALBUMS_PER_USER = 200
MAX_TRACKS = 2_000


def _owned(db: Session, album_id: uuid.UUID, user: User, *, lock: bool = False) -> PrivateAlbum:
    stmt = select(PrivateAlbum).where(PrivateAlbum.id == album_id, PrivateAlbum.owner_id == user.id)
    album = db.scalar(stmt.with_for_update(of=PrivateAlbum) if lock else stmt)
    if album is None:  # 404 for other people's albums: their existence isn't revealed
        raise NotFound("Album not found")
    return album


def _counts(db: Session, ids: list[uuid.UUID]) -> dict:
    if not ids:
        return {}
    return {
        a: n
        for a, n in db.execute(
            select(PrivateAlbumTrack.album_id, func.count()).where(PrivateAlbumTrack.album_id.in_(ids)).group_by(PrivateAlbumTrack.album_id)
        )
    }


def summarize(db: Session, albums: list[PrivateAlbum]) -> list[PrivateAlbumSummary]:
    counts = _counts(db, [a.id for a in albums])
    return [
        PrivateAlbumSummary(
            id=a.id,
            name=a.name,
            description=a.description,
            cover_url=a.cover_url,
            is_public=a.is_public,
            is_favorite=a.is_favorite,
            owner=UserPublic.model_validate(a.owner),
            track_count=counts.get(a.id, 0),
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in albums
    ]


def list_mine(db: Session, user: User, *, sort: AlbumSort, favorites_only: bool, q: str | None) -> list[PrivateAlbumSummary]:
    stmt = select(PrivateAlbum).where(PrivateAlbum.owner_id == user.id)
    if favorites_only:
        stmt = stmt.where(PrivateAlbum.is_favorite.is_(True))
    if q:
        stmt = stmt.where(PrivateAlbum.name.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    counts = select(PrivateAlbumTrack.album_id, func.count().label("n")).group_by(PrivateAlbumTrack.album_id).subquery()
    stmt = stmt.outerjoin(counts, counts.c.album_id == PrivateAlbum.id)
    order = {
        "updated": (PrivateAlbum.updated_at.desc(),),
        "created": (PrivateAlbum.created_at.desc(),),
        "name": (func.lower(PrivateAlbum.name),),
        "tracks": (func.coalesce(counts.c.n, 0).desc(), PrivateAlbum.name),
    }[sort]
    # Favorites float to the top of every ordering.
    albums = db.scalars(stmt.order_by(PrivateAlbum.is_favorite.desc(), *order, PrivateAlbum.id)).unique().all()
    return summarize(db, list(albums))


def create(db: Session, user: User, data: PrivateAlbumCreate) -> PrivateAlbum:
    owned = db.scalar(select(func.count()).where(PrivateAlbum.owner_id == user.id)) or 0
    if owned >= MAX_ALBUMS_PER_USER:
        raise AppError(f"You can keep up to {MAX_ALBUMS_PER_USER} private albums", code="limit_reached", status_code=409)
    album = PrivateAlbum(
        owner_id=user.id,
        name=data.name.strip(),
        description=data.description,
        is_public=data.is_public,
        is_favorite=data.is_favorite,
        share_code=generate_invite_code() if data.is_public else None,
    )
    db.add(album)
    db.commit()
    return album


def update(db: Session, album_id: uuid.UUID, user: User, data: PrivateAlbumUpdate) -> PrivateAlbum:
    album = _owned(db, album_id, user, lock=True)
    fields = data.model_fields_set
    if data.name is not None:
        album.name = data.name.strip()
    if data.description is not None:
        album.description = data.description
    if data.is_favorite is not None:
        album.is_favorite = data.is_favorite
    if data.is_public is not None and data.is_public != album.is_public:
        album.is_public = data.is_public
        album.share_code = (album.share_code or generate_invite_code()) if data.is_public else None  # unsharing kills old links
    if "cover_song_id" in fields and data.cover_song_id is not None:
        in_album = db.scalar(
            select(PrivateAlbumTrack.id).where(PrivateAlbumTrack.album_id == album.id, PrivateAlbumTrack.song_id == data.cover_song_id)
        )
        song = db.get(Song, data.cover_song_id) if in_album else None
        if song is None:
            raise AppError("That track isn't in this album", code="validation_error", status_code=422)
        album.cover_url = (song.album.cover_url if song.album else None) or song.artwork_url
    db.commit()
    return album


def set_cover(db: Session, album_id: uuid.UUID, user: User, upload: UploadFile) -> PrivateAlbum:
    album = _owned(db, album_id, user, lock=True)
    album.cover_url = catalog_svc._replace_image(album.cover_url, upload, "images/private-albums")
    db.commit()
    return album


def rotate_share_code(db: Session, album_id: uuid.UUID, user: User) -> PrivateAlbum:
    album = _owned(db, album_id, user, lock=True)
    if not album.is_public:
        raise Conflict("Make the album public before sharing it")
    album.share_code = generate_invite_code()
    db.commit()
    return album


def delete(db: Session, album_id: uuid.UUID, user: User) -> None:
    album = _owned(db, album_id, user, lock=True)
    db.delete(album)
    db.commit()


def add_tracks(db: Session, album_id: uuid.UUID, user: User, song_ids: list[uuid.UUID]) -> PrivateAlbum:
    album = _owned(db, album_id, user, lock=True)
    existing = set(db.scalars(select(PrivateAlbumTrack.song_id).where(PrivateAlbumTrack.album_id == album.id)))
    found = set(db.scalars(select(Song.id).where(Song.id.in_(song_ids), Song.is_published.is_(True))))
    if len(found) != len(set(song_ids)):
        raise NotFound("One or more tracks don't exist")
    position = db.scalar(select(func.coalesce(func.max(PrivateAlbumTrack.position), -1)).where(PrivateAlbumTrack.album_id == album.id)) + 1
    fresh = [s for s in dict.fromkeys(song_ids) if s not in existing]  # adding a track twice is a no-op
    if len(existing) + len(fresh) > MAX_TRACKS:
        raise AppError(f"An album can hold {MAX_TRACKS} tracks", code="limit_reached", status_code=409)
    for offset, song_id in enumerate(fresh):
        db.add(PrivateAlbumTrack(album_id=album.id, song_id=song_id, position=position + offset))
    if fresh:
        album.updated_at = func.now()
        first = db.get(Song, fresh[0])
        if album.cover_url is None and first is not None:  # the first track's artwork becomes the default cover
            album.cover_url = (first.album.cover_url if first.album else None) or first.artwork_url
    db.commit()
    return album


def remove_track(db: Session, album_id: uuid.UUID, user: User, item_id: int) -> PrivateAlbum:
    album = _owned(db, album_id, user, lock=True)
    item = db.get(PrivateAlbumTrack, item_id)
    if item is None or item.album_id != album.id:
        raise NotFound("Track not in this album")
    db.delete(item)
    db.flush()
    for position, row in enumerate(
        db.scalars(select(PrivateAlbumTrack).where(PrivateAlbumTrack.album_id == album.id).order_by(PrivateAlbumTrack.position)).unique()
    ):
        row.position = position  # keep positions contiguous
    album.updated_at = func.now()
    db.commit()
    return album


def get_viewable(db: Session, album_id: uuid.UUID, user: User | None) -> PrivateAlbum:
    album = db.get(PrivateAlbum, album_id)
    if album is None or not (user is not None and album.owner_id == user.id):
        raise NotFound("Album not found")
    return album


def get_shared(db: Session, code: str) -> PrivateAlbum:
    album = db.scalar(select(PrivateAlbum).where(PrivateAlbum.share_code == code, PrivateAlbum.is_public.is_(True)))
    if album is None:
        raise NotFound("Album not found")
    return album


def detail(db: Session, album: PrivateAlbum, user: User | None) -> PrivateAlbumDetail:
    items = (
        db.scalars(select(PrivateAlbumTrack).where(PrivateAlbumTrack.album_id == album.id).order_by(PrivateAlbumTrack.position))
        .unique()
        .all()
    )
    songs = catalog_svc.song_outs(db, user, [i.song for i in items])
    tracks = [PrivateAlbumTrackOut(id=i.id, position=i.position, added_at=i.added_at, song=s) for i, s in zip(items, songs, strict=True)]
    is_owner = user is not None and album.owner_id == user.id
    summary = summarize(db, [album])[0]
    return PrivateAlbumDetail(
        **summary.model_dump(),
        tracks=tracks,
        total_duration_ms=sum(t.song.duration_ms for t in tracks),
        is_owner=is_owner,
        share_code=album.share_code if is_owner and album.is_public else None,
        share_path=f"/shared/{album.share_code}" if album.is_public and album.share_code else None,
    )

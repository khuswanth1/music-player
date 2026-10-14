import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Literal

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, true
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import (
    LOCAL_SOURCE,
    Album,
    Artist,
    Availability,
    FollowedArtist,
    Genre,
    LikedSong,
    ListeningHistory,
    SavedAlbum,
    Song,
)

SongSort = Literal["popular", "newest", "title", "duration"]
AlbumSort = Literal["newest", "oldest", "title"]


def active_sources() -> list[str]:
    """`local` plus every provider currently enabled; tracks from switched-off sources can't be played."""
    from app.music.providers import enabled_providers  # deferred: providers import settings and models

    return [LOCAL_SOURCE, *(p.key for p in enabled_providers())]


def song_country() -> ColumnElement:
    """A song's country: where it was released when a provider says so, else its artist's country as MusicBrainz lists it."""
    return func.coalesce(Song.country, select(Artist.country).where(Artist.id == Song.artist_id).correlate(Song).scalar_subquery())


def complete_recordings() -> ColumnElement[bool]:
    """Excludes 30-second provider previews unless MUSIC_PREVIEWS_VISIBLE is on."""
    if get_settings().music_previews_visible:
        return true()
    return or_(Song.license_code.is_(None), Song.license_code != "preview")


def playable_condition() -> ColumnElement[bool]:
    """Published, rights-cleared, streamable and from an active source: what lists, charts and
    recommendations may offer."""
    return and_(Song.is_published.is_(True), Song.availability == Availability.playable, Song.stream_allowed.is_(True),
                Song.source.in_(active_sources()), complete_recordings())


def paginate(db: Session, stmt: Select, offset: int, limit: int) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.offset(offset).limit(limit)).unique().all()
    return list(items), total


def songs_query(*, genre_slug: str | None = None, artist_id: uuid.UUID | None = None,
                album_id: uuid.UUID | None = None, include_unpublished: bool = False,
                sort: SongSort = "popular") -> Select:
    stmt = select(Song)
    if not include_unpublished:
        stmt = stmt.where(Song.is_published.is_(True))
    if genre_slug:
        stmt = stmt.join(Genre, Song.genre_id == Genre.id).where(Genre.slug == genre_slug)
    if artist_id:
        stmt = stmt.where(Song.artist_id == artist_id)
    if album_id:
        stmt = stmt.where(Song.album_id == album_id)
    order = {
        "popular": (Song.play_count.desc(), Song.title),
        "newest": (Song.created_at.desc(), Song.id),
        "title": (func.lower(Song.title), Song.id),
        "duration": (Song.duration_ms, Song.id),
    }[sort]
    return stmt.order_by(*order)


def albums_query(*, artist_id: uuid.UUID | None = None, genre_slug: str | None = None,
                 album_type: str | None = None, featured: bool | None = None,
                 sort: AlbumSort = "newest") -> Select:
    stmt = select(Album)
    if artist_id:
        stmt = stmt.where(Album.artist_id == artist_id)
    if album_type:
        stmt = stmt.where(Album.album_type == album_type)
    if featured is not None:
        stmt = stmt.where(Album.is_featured.is_(featured))
    if genre_slug:
        stmt = stmt.where(Album.id.in_(
            select(Song.album_id).join(Genre, Song.genre_id == Genre.id).where(Genre.slug == genre_slug)))
    order = {"newest": (Album.release_date.desc().nulls_last(), Album.id), "oldest": (Album.release_date.nulls_last(), Album.id),
             "title": (func.lower(Album.title), Album.id)}[sort]
    return stmt.order_by(*order)


def artists_query(*, genre_slug: str | None = None, sort: str = "name") -> Select:
    stmt = select(Artist)
    if genre_slug:
        stmt = stmt.where(Artist.id.in_(
            select(Song.artist_id).join(Genre, Song.genre_id == Genre.id).where(Genre.slug == genre_slug)))
    if sort == "popular":
        plays = (select(func.coalesce(func.sum(Song.play_count), 0)).where(Song.artist_id == Artist.id)
                 .correlate(Artist).scalar_subquery())
        return stmt.order_by(plays.desc(), Artist.name)
    return stmt.order_by(func.lower(Artist.name), Artist.id)


def liked_song_ids(db: Session, user_id: uuid.UUID, song_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
    if not song_ids:
        return set()
    return set(db.scalars(select(LikedSong.song_id).where(LikedSong.user_id == user_id,
                                                          LikedSong.song_id.in_(song_ids))))


def artist_follower_count(db: Session, artist_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).where(FollowedArtist.artist_id == artist_id)) or 0


def artist_monthly_plays(db: Session, artist_id: uuid.UUID) -> int:
    since = utcnow() - timedelta(days=30)
    return db.scalar(select(func.count()).select_from(ListeningHistory)
                     .join(Song, Song.id == ListeningHistory.song_id)
                     .where(Song.artist_id == artist_id, ListeningHistory.played_at >= since)) or 0


def is_following(db: Session, user_id: uuid.UUID, artist_id: uuid.UUID) -> bool:
    return db.get(FollowedArtist, (user_id, artist_id)) is not None


def is_album_saved(db: Session, user_id: uuid.UUID, album_id: uuid.UUID) -> bool:
    return db.get(SavedAlbum, (user_id, album_id)) is not None


def slug_exists(db: Session, model, slug: str, exclude_id=None) -> bool:
    stmt = select(model.id).where(model.slug == slug)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return db.scalar(stmt) is not None

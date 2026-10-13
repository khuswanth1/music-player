import logging
import re
import unicodedata
import uuid
from collections.abc import Sequence

from fastapi import UploadFile
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.permissions import Perm, has_permission
from app.models import Album, Artist, Genre, Language, Song, User
from app.repositories import catalog as repo
from app.schemas.catalog import (
    AlbumCreate,
    AlbumDetail,
    AlbumOut,
    AlbumUpdate,
    ArtistCreate,
    ArtistDetail,
    ArtistUpdate,
    GenreCreate,
    GenreUpdate,
    SongOut,
    SongUpdate,
)
from app.storage.backends import get_storage, media_url
from app.storage.validation import validate_audio, validate_image

log = logging.getLogger(__name__)


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "item"


def unique_slug(db: Session, model, name: str, exclude_id=None) -> str:
    base = slugify(name)[:120]
    slug, n = base, 2
    while repo.slug_exists(db, model, slug, exclude_id):
        slug, n = f"{base}-{n}", n + 1
    return slug


def is_staff(user: User | None) -> bool:
    return user is not None and has_permission(user.role_name, Perm.catalog_write)


def song_outs(db: Session, user: User | None, songs: Sequence[Song]) -> list[SongOut]:
    """Serialize songs, adding the per-user `liked` flag with a single query."""
    liked = repo.liked_song_ids(db, user.id, [s.id for s in songs]) if user else set()
    active = set(repo.active_sources())
    out = []
    for song in songs:
        item = SongOut.model_validate(song)
        item.liked = (song.id in liked) if user else None
        if item.playable and song.source not in active:
            item.playable, item.download_allowed = False, False
            item.restriction_reason = "This source is currently disabled on this server"
        out.append(item)
    return out


def _replace_image(old_url: str | None, upload: UploadFile, prefix: str) -> str:
    image = validate_image(upload)
    key = image.key(prefix)
    storage = get_storage()
    with image.fileobj:
        storage.save(key, image.fileobj, image.content_type)
    if old_url and old_url.startswith(f"/api/v1/media/{prefix}/"):
        storage.delete(old_url.removeprefix("/api/v1/media/"))
    return media_url(key)


# --- genres --------------------------------------------------------------------------------

def get_genre_by_slug(db: Session, slug: str) -> Genre:
    genre = db.scalar(select(Genre).where(Genre.slug == slug))
    if genre is None:
        raise NotFound("Genre not found")
    return genre


def create_genre(db: Session, data: GenreCreate) -> Genre:
    if db.scalar(select(Genre).where(Genre.name.ilike(data.name.strip()))):
        raise Conflict("A genre with that name already exists")
    genre = Genre(name=data.name.strip(), slug=unique_slug(db, Genre, data.name), color=data.color)
    db.add(genre)
    db.commit()
    return genre


def update_genre(db: Session, genre_id: int, data: GenreUpdate) -> Genre:
    genre = db.get(Genre, genre_id)
    if genre is None:
        raise NotFound("Genre not found")
    if data.name is not None and data.name.strip() != genre.name:
        genre.name = data.name.strip()
        genre.slug = unique_slug(db, Genre, genre.name, exclude_id=genre.id)
    if data.color is not None:
        genre.color = data.color
    db.commit()
    return genre


def delete_genre(db: Session, genre_id: int) -> None:
    genre = db.get(Genre, genre_id)
    if genre is None:
        raise NotFound("Genre not found")
    db.delete(genre)  # songs keep existing with genre_id set to NULL
    db.commit()


# --- artists -------------------------------------------------------------------------------

def get_artist(db: Session, artist_id: uuid.UUID) -> Artist:
    artist = db.get(Artist, artist_id)
    if artist is None:
        raise NotFound("Artist not found")
    return artist


def artist_detail(db: Session, artist: Artist, user: User | None) -> ArtistDetail:
    return ArtistDetail(
        **{f: getattr(artist, f) for f in ("id", "name", "slug", "bio", "image_url", "verified")},
        follower_count=repo.artist_follower_count(db, artist.id),
        monthly_plays=repo.artist_monthly_plays(db, artist.id),
        is_followed=repo.is_following(db, user.id, artist.id) if user else None,
    )


def create_artist(db: Session, data: ArtistCreate) -> Artist:
    artist = Artist(name=data.name.strip(), slug=unique_slug(db, Artist, data.name), bio=data.bio,
                    verified=data.verified)
    db.add(artist)
    db.commit()
    return artist


def update_artist(db: Session, artist_id: uuid.UUID, data: ArtistUpdate) -> Artist:
    artist = get_artist(db, artist_id)
    if data.name is not None and data.name.strip() != artist.name:
        artist.name = data.name.strip()
        artist.slug = unique_slug(db, Artist, artist.name, exclude_id=artist.id)
    if data.bio is not None:
        artist.bio = data.bio
    if data.verified is not None:
        artist.verified = data.verified
    db.commit()
    return artist


def set_artist_image(db: Session, artist_id: uuid.UUID, upload: UploadFile) -> Artist:
    artist = get_artist(db, artist_id)
    artist.image_url = _replace_image(artist.image_url, upload, "images/artists")
    db.commit()
    return artist


def delete_artist(db: Session, artist_id: uuid.UUID) -> None:
    artist = get_artist(db, artist_id)
    has_content = db.scalar(select(exists().where(Song.artist_id == artist.id))) or \
        db.scalar(select(exists().where(Album.artist_id == artist.id)))
    if has_content:
        raise Conflict("Delete or reassign this artist's albums and songs first", code="artist_has_content")
    db.delete(artist)
    db.commit()


# --- albums --------------------------------------------------------------------------------

def get_album(db: Session, album_id: uuid.UUID) -> Album:
    album = db.get(Album, album_id)
    if album is None:
        raise NotFound("Album not found")
    return album


def album_detail(db: Session, album: Album, user: User | None) -> AlbumDetail:
    stmt = repo.songs_query(album_id=album.id, include_unpublished=is_staff(user))
    songs = db.scalars(stmt.order_by(None).order_by(Song.track_number.nulls_last(), Song.title)).unique().all()
    return AlbumDetail(
        **AlbumOut.model_validate(album).model_dump(),
        songs=song_outs(db, user, songs),
        total_duration_ms=sum(s.duration_ms for s in songs),
        is_saved=repo.is_album_saved(db, user.id, album.id) if user else None,
    )


def create_album(db: Session, data: AlbumCreate) -> Album:
    get_artist(db, data.artist_id)
    album = Album(**data.model_dump())
    db.add(album)
    db.commit()
    db.refresh(album)
    return album


def update_album(db: Session, album_id: uuid.UUID, data: AlbumUpdate) -> Album:
    album = get_album(db, album_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("artist_id"):
        get_artist(db, changes["artist_id"])
    for field, value in changes.items():
        if value is not None:
            setattr(album, field, value)
    db.commit()
    db.refresh(album)
    return album


def set_album_cover(db: Session, album_id: uuid.UUID, upload: UploadFile) -> Album:
    album = get_album(db, album_id)
    album.cover_url = _replace_image(album.cover_url, upload, "images/covers")
    db.commit()
    return album


def delete_album(db: Session, album_id: uuid.UUID) -> None:
    album = get_album(db, album_id)
    db.delete(album)  # songs remain as singles (album_id → NULL)
    db.commit()


# --- songs ---------------------------------------------------------------------------------

def get_song(db: Session, song_id: uuid.UUID, user: User | None = None) -> Song:
    song = db.get(Song, song_id)
    if song is None or (not song.is_published and not is_staff(user)):
        raise NotFound("Song not found")
    return song


def _check_refs(db: Session, *, artist_id=None, album_id=None, genre_id=None) -> None:
    if artist_id is not None:
        get_artist(db, artist_id)
    if album_id is not None:
        get_album(db, album_id)
    if genre_id is not None and db.get(Genre, genre_id) is None:
        raise NotFound("Genre not found")


def create_song(db: Session, *, title: str, artist_id: uuid.UUID, album_id: uuid.UUID | None,
                genre_id: int | None, track_number: int | None, explicit: bool, is_premium: bool,
                is_published: bool, audio: UploadFile) -> Song:
    title = title.strip()
    if not title or len(title) > 200:
        raise AppError("Title must be 1–200 characters", code="validation_error", status_code=422)
    _check_refs(db, artist_id=artist_id, album_id=album_id, genre_id=genre_id)
    validated = validate_audio(audio)
    key = validated.key("audio")
    with validated.fileobj:
        get_storage().save(key, validated.fileobj, validated.content_type)
    song = Song(title=title, artist_id=artist_id, album_id=album_id, genre_id=genre_id,
                track_number=track_number, explicit=explicit, is_premium=is_premium,
                is_published=is_published, duration_ms=validated.duration_ms, audio_key=key,
                audio_mime=validated.content_type, audio_size=validated.size)
    db.add(song)
    try:
        db.commit()
    except Exception:
        db.rollback()
        get_storage().delete(key)  # don't leave orphaned audio behind
        raise
    db.refresh(song)
    log.info("catalog.song_created", extra={"song_id": str(song.id)})
    return song


def replace_song_audio(db: Session, song_id: uuid.UUID, audio: UploadFile) -> Song:
    song = db.get(Song, song_id)
    if song is None:
        raise NotFound("Song not found")
    validated = validate_audio(audio)
    key = validated.key("audio")
    with validated.fileobj:
        get_storage().save(key, validated.fileobj, validated.content_type)
    old_key = song.audio_key
    song.audio_key, song.audio_mime, song.audio_size = key, validated.content_type, validated.size
    song.duration_ms = validated.duration_ms
    db.commit()
    if old_key:
        get_storage().delete(old_key)
    return song


def update_song(db: Session, song_id: uuid.UUID, data: SongUpdate) -> Song:
    song = db.get(Song, song_id)
    if song is None:
        raise NotFound("Song not found")
    changes = data.model_dump(exclude_unset=True)
    _check_refs(db, artist_id=changes.get("artist_id"), album_id=changes.get("album_id"),
                genre_id=changes.get("genre_id"))
    if changes.get("is_premium") and not song.is_local:
        raise AppError("Tracks from open catalogs can't be put behind Premium: many licenses are non-commercial "
                       "and provider terms don't allow it", code="premium_not_allowed", status_code=422)
    if "language" in changes:
        code = changes.pop("language")
        if code is not None and db.get(Language, code) is None:
            raise AppError("Unknown language code", code="validation_error", status_code=422)
        song.language, song.language_source = code, "manual" if code else None
    nullable = {"album_id", "genre_id", "track_number"}
    for field, value in changes.items():
        if value is not None or field in nullable:
            setattr(song, field, value)
    db.commit()
    db.refresh(song)
    return song


def delete_song(db: Session, song_id: uuid.UUID) -> None:
    song = db.get(Song, song_id)
    if song is None:
        raise NotFound("Song not found")
    key = song.audio_key
    db.delete(song)
    db.commit()
    if key:
        get_storage().delete(key)

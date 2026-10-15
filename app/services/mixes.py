"""Personal mixes: playlists that exist for one person only, built from what they chose and what they play.

Nothing is stored. A mix is a recipe (`kind` + `key`) that is re-evaluated on request, so it follows the person's
languages, genres, follows and listening as those change. Tracks are shuffled with a per-person, per-day seed: the
same person sees a stable mix all day, a fresh one tomorrow, and nobody else sees the same order.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Select, String, cast, func, select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import Artist, FollowedArtist, Genre, Language, ListeningHistory, Song, User
from app.repositories.catalog import playable_condition

MIN_TRACKS = 3  # a mix with fewer songs than this isn't offered
MAX_MIXES = 10
SIZE = 30

_COLORS = ["#1e6b4f", "#8d3b72", "#2a5db0", "#b0552a", "#6b4fbf", "#a8324a", "#2f7d8c", "#7a6a1e", "#3d6b2a", "#a1448f"]


@dataclass
class Mix:
    id: str
    kind: str  # on_repeat | discover | language | genre | artist
    title: str
    subtitle: str
    color: str
    songs: list[Song]


def _color(key: str) -> str:
    return _COLORS[sum(map(ord, key)) % len(_COLORS)]


def _daily(user: User, stmt: Select, limit: int) -> Select:
    """Order by a hash of (person, song, day): a stable shuffle that differs per person and changes daily."""
    seed = f"{user.id}:{utcnow().date()}:"
    return stmt.order_by(func.md5(func.concat(seed, cast(Song.id, String))), Song.id).limit(limit)


def _top(user: User, where: tuple, db: Session, *, pool: int = 120) -> list[Song]:
    """The most played of the matching songs, then a daily per-person shuffle of that pool."""
    best = (select(Song.id).where(playable_condition(), *where)
            .order_by(Song.play_count.desc(), Song.provider_popularity.desc().nulls_last(), Song.id).limit(pool).subquery())
    stmt = select(Song).where(Song.id.in_(select(best.c.id)))
    return list(db.scalars(_daily(user, stmt, SIZE)).unique())


def _on_repeat(db: Session, user: User) -> list[Song]:
    since = utcnow() - timedelta(days=60)
    plays = (select(ListeningHistory.song_id, func.count().label("n")).where(ListeningHistory.user_id == user.id,
             ListeningHistory.played_at >= since).group_by(ListeningHistory.song_id)
             .order_by(func.count().desc()).limit(SIZE).subquery())
    stmt = (select(Song).join(plays, plays.c.song_id == Song.id).where(playable_condition()).order_by(plays.c.n.desc(), Song.id))
    return list(db.scalars(stmt).unique())


def _discover(db: Session, user: User) -> list[Song]:
    """Songs in the person's languages and genres that they have never played."""
    heard = select(ListeningHistory.song_id).where(ListeningHistory.user_id == user.id)
    where = [Song.id.not_in(heard)]
    if user.preferred_languages:
        where.append(Song.language.in_(list(user.preferred_languages)))
    if user.preferred_genres:
        where.append(Song.genre_id.in_(select(Genre.id).where(Genre.slug.in_(list(user.preferred_genres)))))
    return _top(user, tuple(where), db, pool=200)


def _build(db: Session, user: User, kind: str, key: str) -> Mix | None:
    if kind == "on_repeat":
        return Mix("on-repeat", kind, "On Repeat", "Songs you can't stop playing", "#a8324a", _on_repeat(db, user))
    if kind == "discover":
        return Mix("discover", kind, "Discover Mix", "New to you, picked from your tastes", "#2a5db0", _discover(db, user))
    if kind == "language":
        lang = db.get(Language, key)
        if lang is None:
            return None
        return Mix(f"language-{key}", kind, f"{lang.name} Mix", f"Your daily {lang.name} picks", _color(key),
                   _top(user, (Song.language == key,), db))
    if kind == "genre":
        genre = db.scalar(select(Genre).where(Genre.slug == key))
        if genre is None:
            return None
        where: tuple = (Song.genre_id == genre.id,)
        if user.preferred_languages:  # a genre mix leans to the languages they chose
            where += (Song.language.in_(list(user.preferred_languages)),)
        songs = _top(user, where, db)
        if len(songs) < MIN_TRACKS:
            songs = _top(user, (Song.genre_id == genre.id,), db)
        return Mix(f"genre-{key}", kind, f"{genre.name} Mix", f"{genre.name} made for you", genre.color or _color(key), songs)
    if kind == "artist":
        artist = db.scalar(select(Artist).where(Artist.slug == key))
        if artist is None:
            return None
        return Mix(f"artist-{key}", kind, f"{artist.name} Mix", f"{artist.name} and more like it", _color(key),
                   _top(user, (Song.artist_id == artist.id,), db))
    return None


def recipes(db: Session, user: User) -> list[tuple[str, str]]:
    """What this person gets, in order: their own habits first, then each language, genre and followed artist."""
    out: list[tuple[str, str]] = []
    if db.scalar(select(func.count()).select_from(ListeningHistory).where(ListeningHistory.user_id == user.id)):
        out.append(("on_repeat", ""))
    out.append(("discover", ""))
    out += [("language", code) for code in (user.preferred_languages or [])[:3]]
    out += [("genre", slug) for slug in (user.preferred_genres or [])[:3]]
    followed = db.scalars(select(Artist.slug).join(FollowedArtist, FollowedArtist.artist_id == Artist.id)
                          .where(FollowedArtist.user_id == user.id).order_by(FollowedArtist.created_at.desc()).limit(3))
    out += [("artist", slug) for slug in followed]
    return out


def mixes_for(db: Session, user: User) -> list[Mix]:
    result: list[Mix] = []
    for kind, key in recipes(db, user):
        mix = _build(db, user, kind, key)
        if mix and len(mix.songs) >= MIN_TRACKS:
            result.append(mix)
        if len(result) >= MAX_MIXES:
            break
    return result


def mix_by_id(db: Session, user: User, mix_id: str) -> Mix | None:
    if mix_id in ("on-repeat", "discover"):
        return _build(db, user, mix_id.replace("-", "_"), "")
    kind, _, key = mix_id.partition("-")
    return _build(db, user, kind, key) if kind in ("language", "genre", "artist") and key else None


# --- artists, albums and playlists picked for one person ---------------------------------------------

def _taste(db: Session, user: User) -> tuple[list[str], list[int]]:
    """The languages and genre ids this person leans to: what they chose, plus what they like and have been playing."""
    from app.models import LikedSong  # local: keeps the module's import list focused on mixes

    langs = list(user.preferred_languages or [])
    genre_ids = list(db.scalars(select(Genre.id).where(Genre.slug.in_(list(user.preferred_genres or [])))))
    liked = (select(Song.language, Song.genre_id).join(LikedSong, LikedSong.song_id == Song.id)
             .where(LikedSong.user_id == user.id).limit(200))
    for language, genre_id in db.execute(liked):
        if language and language not in langs:
            langs.append(language)
        if genre_id and genre_id not in genre_ids:
            genre_ids.append(genre_id)
    return langs[:6], genre_ids[:6]


def _matches(langs: list[str], genre_ids: list[int]):
    from sqlalchemy import or_

    parts = []
    if langs:
        parts.append(Song.language.in_(langs))
    if genre_ids:
        parts.append(Song.genre_id.in_(genre_ids))
    return or_(*parts) if parts else None


def artists_for(db: Session, user: User, limit: int = 12) -> list[Artist]:
    """Artists whose music fits this person's taste, that they don't follow yet."""
    langs, genre_ids = _taste(db, user)
    fit = _matches(langs, genre_ids)
    followed = select(FollowedArtist.artist_id).where(FollowedArtist.user_id == user.id)
    stmt = (select(Song.artist_id).where(playable_condition(), Song.artist_id.not_in(followed)))
    if fit is not None:
        stmt = stmt.where(fit)
    ids = list(db.scalars(stmt.group_by(Song.artist_id)
                          .order_by(func.coalesce(func.sum(Song.play_count), 0).desc(), func.count().desc(), Song.artist_id)
                          .limit(limit * 3)))
    artists = {a.id: a for a in db.scalars(select(Artist).where(Artist.id.in_(ids))).unique()}
    ranked = [artists[i] for i in ids if i in artists and not artists[i].name.startswith(("#", "@")) and "_" not in artists[i].name]
    return ranked[:limit]


def albums_for(db: Session, user: User, limit: int = 12):
    from app.models import Album

    langs, genre_ids = _taste(db, user)
    fit = _matches(langs, genre_ids)
    stmt = select(Song.album_id).where(playable_condition(), Song.album_id.is_not(None))
    if fit is not None:
        stmt = stmt.where(fit)
    ids = list(db.scalars(stmt.group_by(Song.album_id)
                          .order_by(func.coalesce(func.sum(Song.play_count), 0).desc(), Song.album_id).limit(limit)))
    albums = {a.id: a for a in db.scalars(select(Album).where(Album.id.in_(ids))).unique()}
    return [albums[i] for i in ids if i in albums]


def playlists_for(db: Session, user: User, limit: int = 12):
    """Other people's public playlists with the most songs in this person's languages and genres."""
    from app.models import Playlist, PlaylistTrack

    langs, genre_ids = _taste(db, user)
    fit = _matches(langs, genre_ids)
    stmt = (select(Playlist.id).join(PlaylistTrack, PlaylistTrack.playlist_id == Playlist.id)
            .join(Song, Song.id == PlaylistTrack.song_id)
            .where(Playlist.is_public.is_(True), Playlist.owner_id != user.id))
    if fit is not None:
        stmt = stmt.where(fit)
    ids = list(db.scalars(stmt.group_by(Playlist.id).order_by(func.count().desc(), Playlist.id).limit(limit)))
    by_id = {p.id: p for p in db.scalars(select(Playlist).where(Playlist.id.in_(ids))).unique()}
    return [by_id[i] for i in ids if i in by_id]

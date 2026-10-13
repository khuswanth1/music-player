"""Search, browse and recommendations."""

from datetime import timedelta
from typing import Literal

from sqlalchemy import Select, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import Album, Artist, FollowedArtist, Genre, LikedSong, ListeningHistory, Playlist, Song, User
from app.repositories.catalog import playable_condition

SearchType = Literal["song", "artist", "album", "playlist"]
SearchSort = Literal["relevance", "popular", "newest", "title"]


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _match(column, q: str):
    # ILIKE '%q%' is served by the gin_trgm_ops index; similarity() ranks closer matches first.
    return column.ilike(f"%{_escape_like(q)}%", escape="\\")


def search_songs(q: str, *, genre: str | None, sort: SearchSort) -> Select:
    stmt = (select(Song).join(Artist, Artist.id == Song.artist_id).outerjoin(Album, Album.id == Song.album_id)
            .where(Song.is_published.is_(True),
                   or_(_match(Song.title, q), _match(Artist.name, q), _match(Album.title, q))))
    if genre:
        stmt = stmt.join(Genre, Genre.id == Song.genre_id).where(Genre.slug == genre)
    rank = func.greatest(func.similarity(Song.title, q), func.similarity(Artist.name, q) * 0.8)
    return stmt.order_by(*{
        "relevance": (rank.desc(), Song.play_count.desc(), Song.id),
        "popular": (Song.play_count.desc(), Song.id),
        "newest": (Song.created_at.desc(), Song.id),
        "title": (func.lower(Song.title), Song.id),
    }[sort])


def search_artists(q: str, *, genre: str | None, sort: SearchSort) -> Select:
    stmt = select(Artist).where(_match(Artist.name, q))
    if genre:
        stmt = stmt.where(Artist.id.in_(select(Song.artist_id).join(Genre, Genre.id == Song.genre_id)
                                        .where(Genre.slug == genre)))
    plays = (select(func.coalesce(func.sum(Song.play_count), 0)).where(Song.artist_id == Artist.id)
             .correlate(Artist).scalar_subquery())
    return stmt.order_by(*{
        "relevance": (func.similarity(Artist.name, q).desc(), Artist.id),
        "popular": (plays.desc(), Artist.id),
        "newest": (Artist.created_at.desc(), Artist.id),
        "title": (func.lower(Artist.name), Artist.id),
    }[sort])


def search_albums(q: str, *, genre: str | None, sort: SearchSort) -> Select:
    stmt = (select(Album).join(Artist, Artist.id == Album.artist_id)
            .where(or_(_match(Album.title, q), _match(Artist.name, q))))
    if genre:
        stmt = stmt.where(Album.id.in_(select(Song.album_id).join(Genre, Genre.id == Song.genre_id)
                                       .where(Genre.slug == genre)))
    return stmt.order_by(*{
        "relevance": (func.similarity(Album.title, q).desc(), Album.release_date.desc().nulls_last(), Album.id),
        "popular": (Album.is_featured.desc(), Album.release_date.desc().nulls_last(), Album.id),
        "newest": (Album.release_date.desc().nulls_last(), Album.id),
        "title": (func.lower(Album.title), Album.id),
    }[sort])


def search_playlists(q: str, *, sort: SearchSort) -> Select:
    stmt = select(Playlist).where(Playlist.is_public.is_(True), _match(Playlist.name, q))
    return stmt.order_by(*{
        "relevance": (func.similarity(Playlist.name, q).desc(), Playlist.id),
        "popular": (Playlist.updated_at.desc(), Playlist.id),
        "newest": (Playlist.created_at.desc(), Playlist.id),
        "title": (func.lower(Playlist.name), Playlist.id),
    }[sort])


def popular_songs(limit: int) -> Select:
    return (select(Song).where(playable_condition())
            .order_by(Song.play_count.desc(), Song.provider_popularity.desc().nulls_last(), Song.id).limit(limit))


def trending_songs(db: Session, limit: int) -> list[Song]:
    """Most played in the last 7 days, falling back to all-time popularity. Playable tracks only."""
    since = utcnow() - timedelta(days=7)
    plays = (select(ListeningHistory.song_id, func.count().label("n")).where(ListeningHistory.played_at >= since)
             .group_by(ListeningHistory.song_id).subquery())
    songs = list(db.scalars(select(Song).join(plays, plays.c.song_id == Song.id).where(playable_condition())
                            .order_by(plays.c.n.desc(), Song.id).limit(limit)).unique())
    if len(songs) < limit:
        seen = {s.id for s in songs}
        songs += [s for s in db.scalars(popular_songs(limit * 2)).unique() if s.id not in seen][: limit - len(songs)]
    return songs


def recommendations(db: Session, user: User, limit: int = 20) -> list[Song]:
    """Content-based: weight genres, artists and languages by likes, follows, recent listens and the user's
    preferred languages, then surface popular playable songs they haven't played lately. New users get
    popular songs, in their preferred languages first."""
    since = utcnow() - timedelta(days=60)
    liked = select(Song.genre_id.label("genre_id"), Song.artist_id.label("artist_id"), Song.language.label("language"),
                   literal(3).label("w")).join(LikedSong, LikedSong.song_id == Song.id).where(LikedSong.user_id == user.id)
    played = (select(Song.genre_id, Song.artist_id, Song.language, literal(1))
              .join(ListeningHistory, ListeningHistory.song_id == Song.id)
              .where(ListeningHistory.user_id == user.id, ListeningHistory.played_at >= since))
    signals = liked.union_all(played).subquery()

    genre_scores = dict(db.execute(select(signals.c.genre_id, func.sum(signals.c.w))
                                   .where(signals.c.genre_id.is_not(None)).group_by(signals.c.genre_id)).all())
    artist_scores = dict(db.execute(select(signals.c.artist_id, func.sum(signals.c.w)).group_by(signals.c.artist_id)).all())
    language_scores = dict(db.execute(select(signals.c.language, func.sum(signals.c.w))
                                      .where(signals.c.language.is_not(None)).group_by(signals.c.language)).all())
    for (artist_id,) in db.execute(select(FollowedArtist.artist_id).where(FollowedArtist.user_id == user.id)):
        artist_scores[artist_id] = artist_scores.get(artist_id, 0) + 5
    preferred = list(user.preferred_languages or [])
    for code in preferred:
        language_scores[code] = language_scores.get(code, 0) + 6

    recent = select(ListeningHistory.song_id).where(ListeningHistory.user_id == user.id,
                                                    ListeningHistory.played_at >= utcnow() - timedelta(days=3))
    liked_ids = select(LikedSong.song_id).where(LikedSong.user_id == user.id)
    exclude = (playable_condition(), Song.id.not_in(recent), Song.id.not_in(liked_ids))
    affinity = [c for c in (Song.genre_id.in_(list(genre_scores)) if genre_scores else None,
                            Song.artist_id.in_(list(artist_scores)) if artist_scores else None,
                            Song.language.in_(list(language_scores)) if language_scores else None) if c is not None]
    candidates = list(db.scalars(select(Song).where(*exclude, or_(*affinity))
                                 .order_by(Song.play_count.desc(), Song.provider_popularity.desc().nulls_last())
                                 .limit(300)).unique()) if affinity else []

    def score(song: Song) -> float:
        return (genre_scores.get(song.genre_id, 0) * 2 + artist_scores.get(song.artist_id, 0)
                + language_scores.get(song.language, 0) * 1.5 + song.play_count ** 0.5 / 10
                + (song.provider_popularity or 0) * 2)

    ranked = sorted(candidates, key=score, reverse=True)[:limit]
    if len(ranked) < limit:
        seen = {s.id for s in ranked}
        in_preferred = Song.language.in_(preferred) if preferred else literal(False)
        fallback = db.scalars(select(Song).where(*exclude)
                              .order_by(in_preferred.desc(), Song.play_count.desc(),
                                        Song.provider_popularity.desc().nulls_last(), Song.id)
                              .limit(limit * 2)).unique()
        ranked += [s for s in fallback if s.id not in seen][: limit - len(ranked)]
    return ranked

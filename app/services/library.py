import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.security import utcnow
from app.models import (
    Album,
    Artist,
    FollowedArtist,
    LikedSong,
    ListeningHistory,
    PlayerState,
    SavedAlbum,
    SavedPlaylist,
    Song,
    User,
)
from app.repositories.catalog import paginate
from app.schemas.library import HistoryCreate, PlayerStateIn, PlayerStateOut
from app.services import catalog as catalog_svc
from app.services import playlists as playlist_svc

# A play counts toward popularity after 30 s (or the whole track, if shorter).
PLAY_COUNT_THRESHOLD_MS = 30_000


def _add(db: Session, model, **keys) -> None:
    db.execute(insert(model).values(**keys).on_conflict_do_nothing())
    db.commit()


def _remove(db: Session, model, **keys) -> None:
    db.execute(delete(model).filter_by(**keys))
    db.commit()


# --- likes / follows / saves (idempotent PUT and DELETE) ------------------------------------

def like_song(db: Session, user: User, song_id: uuid.UUID) -> None:
    catalog_svc.get_song(db, song_id, user)
    _add(db, LikedSong, user_id=user.id, song_id=song_id)


def unlike_song(db: Session, user: User, song_id: uuid.UUID) -> None:
    _remove(db, LikedSong, user_id=user.id, song_id=song_id)


def liked_songs(db: Session, user: User, offset: int, limit: int):
    stmt = select(LikedSong).where(LikedSong.user_id == user.id).order_by(LikedSong.created_at.desc())
    return paginate(db, stmt, offset, limit)


def follow_artist(db: Session, user: User, artist_id: uuid.UUID) -> None:
    if db.get(Artist, artist_id) is None:
        raise NotFound("Artist not found")
    _add(db, FollowedArtist, user_id=user.id, artist_id=artist_id)


def unfollow_artist(db: Session, user: User, artist_id: uuid.UUID) -> None:
    _remove(db, FollowedArtist, user_id=user.id, artist_id=artist_id)


def save_album(db: Session, user: User, album_id: uuid.UUID) -> None:
    if db.get(Album, album_id) is None:
        raise NotFound("Album not found")
    _add(db, SavedAlbum, user_id=user.id, album_id=album_id)


def unsave_album(db: Session, user: User, album_id: uuid.UUID) -> None:
    _remove(db, SavedAlbum, user_id=user.id, album_id=album_id)


def save_playlist(db: Session, user: User, playlist_id: uuid.UUID) -> None:
    playlist_svc.get_viewable(db, playlist_id, user)
    _add(db, SavedPlaylist, user_id=user.id, playlist_id=playlist_id)


def unsave_playlist(db: Session, user: User, playlist_id: uuid.UUID) -> None:
    _remove(db, SavedPlaylist, user_id=user.id, playlist_id=playlist_id)


# --- listening history ---------------------------------------------------------------------

def record_play(db: Session, user: User, data: HistoryCreate) -> ListeningHistory:
    song = catalog_svc.get_song(db, data.song_id, user)
    entry = ListeningHistory(user_id=user.id, song_id=song.id, ms_played=data.ms_played,
                             completed=data.completed, context_type=data.context_type, context_id=data.context_id)
    db.add(entry)
    if data.ms_played >= min(PLAY_COUNT_THRESHOLD_MS, song.duration_ms) or data.completed:
        # Atomic increment; never read-modify-write a counter.
        db.execute(update(Song).where(Song.id == song.id).values(play_count=Song.play_count + 1))
    db.commit()
    db.refresh(entry)
    return entry


def history(db: Session, user: User, offset: int, limit: int):
    stmt = (select(ListeningHistory).where(ListeningHistory.user_id == user.id)
            .order_by(ListeningHistory.played_at.desc(), ListeningHistory.id.desc()))
    return paginate(db, stmt, offset, limit)


def recently_played_songs(db: Session, user: User, limit: int = 12) -> list[Song]:
    """Distinct songs, most recent play first."""
    latest = (select(ListeningHistory.song_id, func.max(ListeningHistory.played_at).label("last"))
              .where(ListeningHistory.user_id == user.id,
                     ListeningHistory.played_at >= utcnow() - timedelta(days=90))
              .group_by(ListeningHistory.song_id).subquery())
    stmt = (select(Song).join(latest, latest.c.song_id == Song.id).where(Song.is_published.is_(True))
            .order_by(latest.c.last.desc()).limit(limit))
    return list(db.scalars(stmt).unique())


def clear_history(db: Session, user: User) -> None:
    db.execute(delete(ListeningHistory).where(ListeningHistory.user_id == user.id))
    db.commit()


# --- persistent player state ---------------------------------------------------------------

def get_player(db: Session, user: User) -> PlayerStateOut:
    state = db.get(PlayerState, user.id)
    if state is None:
        return PlayerStateOut(current_song=None, position_ms=0, queue=[], context=None, shuffle=False,
                              repeat_mode="off", volume=0.8, updated_at=None)
    ids = [uuid.UUID(i) for i in state.queue]
    wanted = set(ids) | ({state.current_song_id} if state.current_song_id else set())
    songs = {s.id: s for s in db.scalars(select(Song).where(Song.id.in_(wanted), Song.is_published.is_(True))).unique()}
    queue_songs = [songs[i] for i in ids if i in songs]
    current = songs.get(state.current_song_id) if state.current_song_id else None
    outs = catalog_svc.song_outs(db, user, ([current] if current else []) + queue_songs)
    return PlayerStateOut(current_song=outs[0] if current else None, position_ms=state.position_ms,
                          queue=outs[1:] if current else outs, context=state.context, shuffle=state.shuffle,
                          repeat_mode=state.repeat_mode, volume=state.volume, updated_at=state.updated_at)


def save_player(db: Session, user: User, data: PlayerStateIn) -> None:
    values = {"current_song_id": data.current_song_id, "position_ms": data.position_ms,
              "queue": [str(i) for i in data.queue], "context": data.context, "shuffle": data.shuffle,
              "repeat_mode": data.repeat_mode, "volume": data.volume, "updated_at": utcnow()}
    stmt = insert(PlayerState).values(user_id=user.id, **values)
    db.execute(stmt.on_conflict_do_update(index_elements=[PlayerState.user_id], set_=values))
    db.commit()

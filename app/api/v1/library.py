import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, PageParams
from app.models import Album, Artist, FollowedArtist, LikedSong, SavedAlbum, SavedPlaylist
from app.schemas.catalog import AlbumOut, ArtistOut, SongOut
from app.schemas.common import Message, Page
from app.schemas.library import (
    ContainsResponse,
    HistoryCreate,
    HistoryOut,
    LikedSongOut,
    PlayerStateIn,
    PlayerStateOut,
)
from app.schemas.playlist import PlaylistSummary
from app.services import catalog as catalog_svc
from app.services import library as svc
from app.services.playlists import can_view, summarize_many

router = APIRouter(prefix="/me", tags=["library"])


def _parse_ids(ids: str) -> list[uuid.UUID]:
    out = []
    for raw in ids.split(",")[:100]:
        try:
            out.append(uuid.UUID(raw.strip()))
        except ValueError:
            continue
    return out


# --- liked songs ---------------------------------------------------------------------------

@router.get("/liked-songs", response_model=Page[LikedSongOut])
def liked_songs(user: CurrentUser, db: DB, page: PageParams):
    items, total = svc.liked_songs(db, user, page.offset, page.page_size)
    songs = catalog_svc.song_outs(db, user, [i.song for i in items])
    out = [LikedSongOut(created_at=i.created_at, song=s) for i, s in zip(items, songs, strict=True)]
    return Page.build(out, total, page.page, page.page_size)


@router.get("/liked-songs/contains", response_model=ContainsResponse)
def liked_contains(user: CurrentUser, db: DB, ids: str = Query(..., description="Comma-separated song ids")):
    song_ids = _parse_ids(ids)
    liked = set(db.scalars(select(LikedSong.song_id).where(LikedSong.user_id == user.id,
                                                           LikedSong.song_id.in_(song_ids))))
    return ContainsResponse(ids={str(i): i in liked for i in song_ids})


@router.put("/liked-songs/{song_id}", response_model=Message)
def like(song_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.like_song(db, user, song_id)
    return Message(message="Added to Liked Songs")


@router.delete("/liked-songs/{song_id}", response_model=Message)
def unlike(song_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.unlike_song(db, user, song_id)
    return Message(message="Removed from Liked Songs")


# --- followed artists ----------------------------------------------------------------------

@router.get("/following", response_model=list[ArtistOut])
def following(user: CurrentUser, db: DB):
    return db.scalars(select(Artist).join(FollowedArtist, FollowedArtist.artist_id == Artist.id)
                      .where(FollowedArtist.user_id == user.id).order_by(FollowedArtist.created_at.desc())).all()


@router.put("/following/{artist_id}", response_model=Message)
def follow(artist_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.follow_artist(db, user, artist_id)
    return Message(message="Following")


@router.delete("/following/{artist_id}", response_model=Message)
def unfollow(artist_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.unfollow_artist(db, user, artist_id)
    return Message(message="Unfollowed")


# --- saved albums --------------------------------------------------------------------------

@router.get("/albums", response_model=list[AlbumOut])
def saved_albums(user: CurrentUser, db: DB):
    return db.scalars(select(Album).join(SavedAlbum, SavedAlbum.album_id == Album.id)
                      .where(SavedAlbum.user_id == user.id).order_by(SavedAlbum.created_at.desc())).unique().all()


@router.put("/albums/{album_id}", response_model=Message)
def save_album(album_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.save_album(db, user, album_id)
    return Message(message="Saved to library")


@router.delete("/albums/{album_id}", response_model=Message)
def unsave_album(album_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.unsave_album(db, user, album_id)
    return Message(message="Removed from library")


# --- saved playlists -----------------------------------------------------------------------

@router.get("/saved-playlists", response_model=list[PlaylistSummary])
def saved_playlists(user: CurrentUser, db: DB):
    rows = db.scalars(select(SavedPlaylist).where(SavedPlaylist.user_id == user.id)
                      .order_by(SavedPlaylist.created_at.desc())).unique().all()
    # A saved playlist the owner later made private drops out of the list.
    return summarize_many(db, [r.playlist for r in rows if can_view(db, r.playlist, user)])


@router.put("/saved-playlists/{playlist_id}", response_model=Message)
def save_playlist(playlist_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.save_playlist(db, user, playlist_id)
    return Message(message="Saved to library")


@router.delete("/saved-playlists/{playlist_id}", response_model=Message)
def unsave_playlist(playlist_id: uuid.UUID, user: CurrentUser, db: DB):
    svc.unsave_playlist(db, user, playlist_id)
    return Message(message="Removed from library")


# --- history -------------------------------------------------------------------------------

@router.post("/history", response_model=HistoryOut, status_code=201)
def record_play(data: HistoryCreate, user: CurrentUser, db: DB):
    entry = svc.record_play(db, user, data)
    return HistoryOut(id=entry.id, played_at=entry.played_at, ms_played=entry.ms_played, completed=entry.completed,
                      context_type=entry.context_type, context_id=entry.context_id,
                      song=catalog_svc.song_outs(db, user, [entry.song])[0])


@router.get("/history", response_model=Page[HistoryOut])
def get_history(user: CurrentUser, db: DB, page: PageParams):
    items, total = svc.history(db, user, page.offset, page.page_size)
    songs = catalog_svc.song_outs(db, user, [i.song for i in items])
    out = [HistoryOut(id=i.id, played_at=i.played_at, ms_played=i.ms_played, completed=i.completed,
                      context_type=i.context_type, context_id=i.context_id, song=s)
           for i, s in zip(items, songs, strict=True)]
    return Page.build(out, total, page.page, page.page_size)


@router.get("/recently-played", response_model=list[SongOut])
def recently_played(user: CurrentUser, db: DB, limit: int = Query(12, ge=1, le=50)):
    return catalog_svc.song_outs(db, user, svc.recently_played_songs(db, user, limit))


@router.delete("/history", response_model=Message)
def clear_history(user: CurrentUser, db: DB):
    svc.clear_history(db, user)
    return Message(message="Listening history cleared")


# --- player state --------------------------------------------------------------------------

@router.get("/player", response_model=PlayerStateOut)
def get_player(user: CurrentUser, db: DB):
    return svc.get_player(db, user)


@router.put("/player", response_model=Message)
def save_player(data: PlayerStateIn, user: CurrentUser, db: DB):
    svc.save_player(db, user, data)
    return Message(message="Saved")

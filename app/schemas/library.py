import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.playback import RepeatMode
from app.schemas.catalog import AlbumOut, ArtistOut, SongOut
from app.schemas.common import ORMModel


class LikedSongOut(ORMModel):
    created_at: datetime
    song: SongOut


class FollowedArtistOut(ORMModel):
    created_at: datetime
    artist: ArtistOut


class SavedAlbumOut(ORMModel):
    created_at: datetime
    album: AlbumOut


class HistoryCreate(BaseModel):
    song_id: uuid.UUID
    ms_played: int = Field(ge=0, le=24 * 3600 * 1000)
    completed: bool = False
    # Where the play started (album, playlist, language, chart, ...). The web player reports many kinds and adds new
    # ones over time, so any short slug is accepted instead of a fixed list that 422s a legitimate play.
    context_type: str | None = Field(default=None, pattern="^[a-z][a-z_-]{0,19}$")
    context_id: uuid.UUID | None = None


class HistoryOut(ORMModel):
    id: int
    played_at: datetime
    ms_played: int
    completed: bool
    context_type: str | None
    context_id: uuid.UUID | None
    song: SongOut


class ContainsResponse(BaseModel):
    ids: dict[str, bool]


class PlayerStateIn(BaseModel):
    current_song_id: uuid.UUID | None = None
    position_ms: int = Field(default=0, ge=0)
    queue: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    context: dict | None = None
    shuffle: bool = False
    repeat_mode: RepeatMode = RepeatMode.off
    volume: float = Field(default=0.8, ge=0, le=1)


class PlayerStateOut(BaseModel):
    current_song: SongOut | None
    position_ms: int
    queue: list[SongOut]
    context: dict | None
    shuffle: bool
    repeat_mode: RepeatMode
    volume: float
    updated_at: datetime | None

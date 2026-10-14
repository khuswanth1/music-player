import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.catalog import SongOut
from app.schemas.common import ORMModel
from app.schemas.user import UserPublic

AlbumSort = Literal["updated", "created", "name", "tracks"]


class PrivateAlbumCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    is_public: bool = False
    is_favorite: bool = False


class PrivateAlbumUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_public: bool | None = None
    is_favorite: bool | None = None
    cover_song_id: uuid.UUID | None = Field(default=None, description="Use this track's artwork as the cover")


class PrivateAlbumSummary(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    cover_url: str | None
    is_public: bool
    is_favorite: bool
    owner: UserPublic
    track_count: int
    created_at: datetime
    updated_at: datetime


class PrivateAlbumTrackOut(ORMModel):
    id: int
    position: int
    added_at: datetime
    song: SongOut


class PrivateAlbumDetail(PrivateAlbumSummary):
    tracks: list[PrivateAlbumTrackOut]
    total_duration_ms: int
    is_owner: bool
    share_code: str | None = Field(None, description="Only for the owner of a public album")
    share_path: str | None = Field(None, description="Frontend path that opens this public album")


class AddAlbumTracks(BaseModel):
    song_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)

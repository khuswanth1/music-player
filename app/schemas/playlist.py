import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.catalog import SongOut
from app.schemas.common import ORMModel
from app.schemas.user import UserPublic


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    is_public: bool = True
    is_collaborative: bool = False

    @model_validator(mode="after")
    def _collab_private(self):
        if self.is_collaborative and self.is_public:
            raise ValueError("Collaborative playlists must be private")
        return self


class PlaylistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_public: bool | None = None
    is_collaborative: bool | None = None


class PlaylistSummary(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    cover_url: str | None
    is_public: bool
    is_collaborative: bool
    owner: UserPublic
    track_count: int
    updated_at: datetime


class PlaylistTrackOut(ORMModel):
    id: int
    position: int
    added_at: datetime
    added_by: UserPublic | None
    song: SongOut


class PlaylistDetail(PlaylistSummary):
    tracks: list[PlaylistTrackOut]
    total_duration_ms: int
    collaborators: list[UserPublic]
    can_edit: bool
    is_owner: bool
    is_saved: bool | None = None
    collab_invite_code: str | None = None  # only exposed to the owner


class AddTracksRequest(BaseModel):
    song_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    position: int | None = Field(default=None, ge=0)


class ReorderRequest(BaseModel):
    from_index: int = Field(ge=0)
    to_index: int = Field(ge=0)


class JoinPlaylistRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)

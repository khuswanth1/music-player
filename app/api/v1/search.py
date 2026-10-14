"""Universal search, suggestions and the signed-in listener's search history (+ a few spec-named aliases)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import DB, CurrentUser, OptionalUser, PageParams
from app.api.v1 import library as library_api
from app.api.v1 import playlists as playlists_api
from app.core.errors import AppError
from app.core.rate_limit import rate_limit
from app.music import languages as langs
from app.schemas.common import Message, Page
from app.schemas.library import HistoryOut, LikedSongOut
from app.schemas.playlist import PlaylistSummary
from app.schemas.search import SearchHistoryIn, SearchHistoryItem, SuggestionsOut, UnifiedSearchOut
from app.services import unified_search as svc

router = APIRouter(tags=["search"])
_fanout_limit = rate_limit("music-fanout", limit=30, window=60)
_suggest_limit = Depends(rate_limit("suggest", limit=120, window=60))

CATEGORY_NAMES = set(svc.ALL)


def _language(value: str | None) -> str | None:
    if not value:
        return None
    code = value if value in langs.BY_CODE else langs.normalize(value)
    if code is None:
        raise AppError(f"Unknown language: {value}", code="validation_error", status_code=422)
    return code


@router.get(
    "/search/global",
    response_model=UnifiedSearchOut,
    summary="Search songs, artists, albums, soundtracks, podcasts, episodes, playlists, private albums and facets at once",
)
def global_search(
    request: Request,
    db: DB,
    user: OptionalUser,
    q: Annotated[str, Query(min_length=2, max_length=100, description="Free text; 'telugu old songs 1990' is understood")],
    categories: Annotated[str | None, Query(description=f"Comma-separated subset of: {', '.join(svc.ALL)} (default all)")] = None,
    language: Annotated[str | None, Query(max_length=40)] = None,
    country: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    genre: Annotated[str | None, Query(max_length=60, description="Genre slug")] = None,
    source: Annotated[str | None, Query(max_length=32, description="Provider key, e.g. itunes, jamendo")] = None,
    full_only: Annotated[bool, Query(description="Only complete recordings (no previews, no metadata-only)")] = False,
    page: Annotated[int, Query(ge=1, le=100)] = 1,
    limit: Annotated[int, Query(ge=1, le=40)] = 20,
    live: Annotated[bool, Query(description="false = search only what is already in the catalog (instant, no provider calls)")] = True,
):
    if live:  # only provider fan-out costs quota; the instant catalog-only pass isn't counted
        _fanout_limit(request)
    wanted = {c.strip() for c in categories.split(",")} & CATEGORY_NAMES if categories else set(CATEGORY_NAMES)
    if not wanted:
        raise AppError("Unknown categories", code="validation_error", status_code=422)
    return svc.search(
        db,
        user,
        q.strip(),
        categories=wanted,
        language=_language(language),
        country=country.upper() if country else None,
        year=year,
        genre=genre,
        source=source,
        full_only=full_only,
        page=page,
        limit=limit,
        live=live,
    )


@router.get(
    "/search/suggestions",
    response_model=SuggestionsOut,
    dependencies=[_suggest_limit],
    summary="Autocomplete from the catalog and your recent searches (no provider calls)",
)
def suggestions(db: DB, user: OptionalUser, q: Annotated[str, Query(min_length=1, max_length=100)], limit: int = Query(10, ge=1, le=20)):
    return svc.suggestions(db, user, q, limit)


@router.get("/me/search-history", response_model=list[SearchHistoryItem])
def search_history(db: DB, user: CurrentUser, limit: int = Query(10, ge=1, le=50)):
    return [SearchHistoryItem(query=q, last_searched_at=t) for q, t in svc.recent_searches(db, user, limit)]


@router.post("/me/search-history", response_model=Message, status_code=201)
def add_search_history(data: SearchHistoryIn, db: DB, user: CurrentUser):
    svc.record_search(db, user, data.query)
    return Message(message="Saved")


@router.delete("/me/search-history", response_model=Message, summary="Clear all, or one query with ?query=")
def clear_search_history(db: DB, user: CurrentUser, query: Annotated[str | None, Query(max_length=100)] = None):
    svc.clear_search(db, user, query)
    return Message(message="Cleared")


# --- aliases for the documented resource names ----------------------------------------------------


@router.get("/users/history", response_model=Page[HistoryOut], tags=["users"], summary="Listening history (same as /me/history)")
def users_history(user: CurrentUser, db: DB, page: PageParams):
    return library_api.get_history(user, db, page)


@router.get(
    "/users/favorites", response_model=Page[LikedSongOut], tags=["users"], summary="Favorite (liked) songs (same as /me/liked-songs)"
)
def users_favorites(user: CurrentUser, db: DB, page: PageParams):
    return library_api.liked_songs(user, db, page)


@router.get("/playlists", response_model=list[PlaylistSummary], tags=["playlists"], summary="My playlists (same as /me/playlists)")
def list_playlists(user: CurrentUser, db: DB):
    return playlists_api.my_playlists(user, db)

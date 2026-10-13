"""Open music catalogs: languages, providers, federated search, charts, downloads and rights."""

import uuid
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.api.deps import DB, CurrentUser, OptionalUser, PageParams, require_permission
from app.billing import webhooks
from app.core.config import get_settings
from app.core.errors import AppError, Forbidden, NotFound
from app.core.permissions import Perm
from app.core.rate_limit import rate_limit
from app.core.security import utcnow
from app.db.session import SessionLocal
from app.models import CatalogSyncState, Genre, Language, ProviderUsage, Song, User
from app.music import charts as chart_svc
from app.music import federation, rights
from app.music import languages as langs
from app.music.ingest import recheck_rights
from app.music.providers import get_provider, is_enabled, known_providers
from app.repositories.catalog import paginate, playable_condition
from app.schemas.catalog import SongOut
from app.schemas.common import Page
from app.schemas.music import (
    AdminProviderOut,
    CatalogWebhookEvent,
    ChartDetail,
    ChartEntry,
    ChartOut,
    DownloadOut,
    FetchResultOut,
    GenreCount,
    GlobalSearchOut,
    LanguageDetail,
    LanguageOut,
    MetadataRecordingOut,
    PreferredLanguages,
    ProviderOut,
    ProviderPolicyOut,
    ProviderStatusOut,
    ProviderUsageOut,
    SyncRequest,
    SyncStateOut,
    TakedownRequest,
)
from app.services import catalog as catalog_svc

router = APIRouter()
CatalogEditor = Annotated[User, Depends(require_permission(Perm.catalog_write))]
# Each of these fans out to several external APIs; keep one client from burning everyone's quota.
_provider_fanout_limit = Depends(rate_limit("music-fanout", limit=30, window=60))

# Auto-fetch from providers when a language page has fewer playable tracks than this.
_WARM_THRESHOLD = 12
_WARM_COOLDOWN = timedelta(hours=6)


def _language_out(lang: Language, total: int, playable: int) -> LanguageOut:
    return LanguageOut(code=lang.code, name=lang.name, native_name=lang.native_name, region=lang.region,
                       region_name=langs.REGIONS.get(lang.region, lang.region), rtl=lang.rtl,
                       featured=lang.featured_rank is not None, track_count=total, playable_count=playable)


def _statuses(statuses) -> list[ProviderStatusOut]:
    return [ProviderStatusOut(key=s.key, name=s.name, status=s.status, count=s.count, message=s.message) for s in statuses]


# --- languages -----------------------------------------------------------------------------------

@router.get("/languages", response_model=list[LanguageOut], tags=["languages"],
            summary="Every supported language with catalog counts (featured first, then by size)")
def list_languages(db: DB, with_tracks: bool = Query(False, description="Only languages that have tracks")):
    counts = (select(Song.language, func.count().label("total"),
                     func.count().filter(playable_condition()).label("playable"))
              .where(Song.is_published.is_(True), Song.language.is_not(None)).group_by(Song.language).subquery())
    rows = db.execute(select(Language, func.coalesce(counts.c.total, 0), func.coalesce(counts.c.playable, 0))
                      .outerjoin(counts, counts.c.language == Language.code)
                      .order_by(Language.featured_rank.nulls_last(), func.coalesce(counts.c.playable, 0).desc(),
                                Language.name)).all()
    return [_language_out(lang, total, playable) for lang, total, playable in rows if total or not with_tracks]


def _get_language(db, code: str) -> Language:
    lang = db.get(Language, code) or db.get(Language, langs.normalize(code) or "")
    if lang is None:
        raise NotFound("Unknown language")
    return lang


@router.get("/languages/{code}", response_model=LanguageDetail, tags=["languages"])
def get_language(code: str, db: DB):
    lang = _get_language(db, code)
    total = db.scalar(select(func.count()).where(Song.language == lang.code, Song.is_published.is_(True))) or 0
    playable = db.scalar(select(func.count()).where(Song.language == lang.code, playable_condition())) or 0
    genres = db.execute(select(Genre, func.count(Song.id)).join(Song, Song.genre_id == Genre.id)
                        .where(Song.language == lang.code, playable_condition()).group_by(Genre.id)
                        .order_by(func.count(Song.id).desc()).limit(12)).all()
    sources = dict(db.execute(select(Song.source, func.count()).where(Song.language == lang.code, playable_condition())
                              .group_by(Song.source)).all())
    return LanguageDetail(**_language_out(lang, total, playable).model_dump(), sources=sources,
                          top_genres=[GenreCount(id=g.id, name=g.name, slug=g.slug, color=g.color, track_count=n)
                                      for g, n in genres])


@router.get("/languages/{code}/tracks", response_model=Page[SongOut], tags=["languages"],
            summary="Tracks in a language. The first page tops itself up from providers when the catalog is thin.")
def language_tracks(code: str, db: DB, user: OptionalUser, page: PageParams, genre: str | None = None,
                    sort: Literal["popular", "newest", "title"] = "popular", playable_only: bool = True):
    lang = _get_language(db, code)
    if page.page == 1 and not genre:
        _warm_language(db, lang.code)
    stmt = select(Song).where(Song.language == lang.code, Song.is_published.is_(True))
    if playable_only:
        stmt = stmt.where(playable_condition())
    if genre:
        stmt = stmt.join(Genre, Genre.id == Song.genre_id).where(Genre.slug == genre)
    stmt = stmt.order_by(*{
        "popular": (Song.play_count.desc(), Song.provider_popularity.desc().nulls_last(), Song.id),
        "newest": (Song.created_at.desc(), Song.id),
        "title": (func.lower(Song.title), Song.id),
    }[sort])
    items, total = paginate(db, stmt, page.offset, page.page_size)
    return Page.build(catalog_svc.song_outs(db, user, items), total, page.page, page.page_size)


def _warm_language(db, code: str) -> None:
    """Fetch from providers once in a while if this language has little to play yet."""
    playable = db.scalar(select(func.count()).where(Song.language == code, playable_condition())) or 0
    if playable >= _WARM_THRESHOLD:
        return
    last = db.scalar(select(func.max(CatalogSyncState.last_synced_at)).where(CatalogSyncState.language == code))
    if last and last > utcnow() - _WARM_COOLDOWN:
        return
    federation.fetch_language(db, code)


@router.post("/languages/{code}/fetch", response_model=FetchResultOut, tags=["languages"],
             dependencies=[_provider_fanout_limit],
             summary="Pull the next page of this language's music from every provider that can filter by language")
def fetch_language(code: str, db: DB, _: CurrentUser):
    lang = _get_language(db, code)
    result = federation.fetch_language(db, lang.code)
    return FetchResultOut(language=lang.code, imported=result.imported, updated=result.updated,
                          providers=_statuses(result.statuses))


@router.get("/me/languages", response_model=PreferredLanguages, tags=["languages"])
def my_languages(user: CurrentUser):
    return PreferredLanguages(languages=user.preferred_languages or [])


@router.put("/me/languages", response_model=PreferredLanguages, tags=["languages"],
            summary="Languages to favour in recommendations and on the home screen")
def set_my_languages(data: PreferredLanguages, user: CurrentUser, db: DB):
    codes: list[str] = []
    for value in data.languages:
        code = value if value in langs.BY_CODE else langs.normalize(value)
        if code is None:
            raise AppError(f"Unknown language: {value}", code="validation_error", status_code=422)
        if code not in codes:
            codes.append(code)
    user.preferred_languages = codes
    db.commit()
    return PreferredLanguages(languages=codes)


# --- providers -----------------------------------------------------------------------------------

def _provider_counts(db) -> dict[str, tuple[int, int]]:
    rows = db.execute(select(Song.source, func.count(), func.count().filter(playable_condition())).group_by(Song.source)).all()
    return {source: (total, playable) for source, total, playable in rows}


def _provider_out(p, counts) -> dict:
    total, playable = counts.get(p.key, (0, 0))
    return dict(key=p.key, name=p.name, description=p.description, homepage=p.homepage, terms_url=p.terms_url,
                attribution_html=p.attribution_html, capabilities=sorted(c.value for c in p.capabilities),
                enabled=is_enabled(p), configured=p.is_configured(), requires_credentials=p.requires_credentials,
                policy=ProviderPolicyOut(stream=p.policy.stream, requires_open_license=p.policy.requires_open_license,
                                         download_links=p.policy.download_links, notes=p.policy.notes),
                track_count=total, playable_count=playable)


@router.get("/providers", response_model=list[ProviderOut], tags=["providers"],
            summary="Music sources, their terms and attribution, and how many tracks each contributes")
def list_providers(db: DB):
    counts = _provider_counts(db)
    return [ProviderOut(**_provider_out(p, counts)) for p in known_providers()]


# --- federated search ----------------------------------------------------------------------------

@router.get("/search/global", response_model=GlobalSearchOut, tags=["discovery"], dependencies=[_provider_fanout_limit],
            summary="Search every enabled provider at once; results are added to the catalog with their rights")
def global_search(db: DB, user: OptionalUser, q: Annotated[str, Query(min_length=2, max_length=100)],
                  language: str | None = None, limit: int = Query(20, ge=1, le=40)):
    code = None
    if language:
        code = _get_language(db, language).code
    found = federation.global_search(db, q.strip(), language=code, limit=limit)
    return GlobalSearchOut(
        query=q.strip(), language=code, songs=catalog_svc.song_outs(db, user, found.songs),
        providers=_statuses(found.statuses),
        metadata_only=[MetadataRecordingOut(**vars(r)) for r in found.metadata_only])


# --- charts --------------------------------------------------------------------------------------

@router.get("/charts", response_model=list[ChartOut], tags=["charts"],
            summary="Charts that have data: global, per region and per language")
def list_charts(db: DB):
    return [ChartOut(**vars(c)) for c in chart_svc.list_charts(db)]


@router.get("/charts/{chart_id}", response_model=ChartDetail, tags=["charts"])
def get_chart(chart_id: str, db: DB, user: OptionalUser, limit: int = Query(50, ge=1, le=100)):
    rows = chart_svc.chart_tracks(db, chart_id, limit)
    songs = catalog_svc.song_outs(db, user, [song for song, _ in rows])
    entries = [ChartEntry(rank=rank, listens_7d=listens, song=song)
               for rank, (song, (_, listens)) in enumerate(zip(songs, rows, strict=True), start=1)]
    return ChartDetail(id=chart_id, title=chart_svc.chart_title(chart_id), basis=chart_svc.BASIS,
                       generated_at=utcnow(), entries=entries)


# --- downloads -----------------------------------------------------------------------------------

@router.get("/songs/{song_id}/download", response_model=DownloadOut, tags=["streaming"],
            summary="Provider download link, only when both the license and the provider's terms allow it")
def download(song_id: uuid.UUID, db: DB, user: CurrentUser):
    song = catalog_svc.get_song(db, song_id, user)
    if song.is_local or not (song.download_allowed and song.playable and song.remote_download_url):
        raise Forbidden("Downloading isn't permitted for this track", code="download_not_permitted")
    provider = get_provider(song.source)
    if provider is None or not is_enabled(provider) or not get_settings().music_downloads_enabled:
        raise Forbidden("Downloading isn't permitted for this track", code="download_not_permitted")
    return DownloadOut(url=song.remote_download_url, license_name=song.license_name, license_url=song.license_url,
                       attribution=song.attribution)


# --- rights notifications (webhook) ------------------------------------------------------------

@router.post("/catalog/webhooks", tags=["webhooks"], status_code=200,
             summary="Signed rights notifications: takedowns, restores, license changes",
             openapi_extra={"requestBody": {"content": {"application/json": {
                 "schema": CatalogWebhookEvent.model_json_schema()}}, "required": True}})
async def catalog_webhook(request: Request, background: BackgroundTasks):
    """Verify `X-Wavely-Signature` (`t=<unix>,v1=<hex HMAC-SHA256 of "t.body" with CATALOG_WEBHOOK_SECRET>`),
    store the event once per `id`, acknowledge, then process it in the background (failures are retried)."""
    payload = await request.body()
    signature = request.headers.get("x-wavely-signature")
    secret = get_settings().catalog_webhook_secret

    def _ingest():
        with SessionLocal() as db:
            event, created = webhooks.ingest(db, payload, signature, provider=rights.WEBHOOK_PROVIDER, secret=secret)
            return event.id, created, event.status

    event_pk, created, status = await run_in_threadpool(_ingest)
    if created:
        background.add_task(webhooks.process_event, event_pk)
    return {"received": True, "duplicate": not created, "status": status.value}


# --- admin ---------------------------------------------------------------------------------------

@router.get("/admin/providers", response_model=list[AdminProviderOut], tags=["admin"])
def admin_providers(_: CatalogEditor, db: DB):
    counts = _provider_counts(db)
    today = {u.provider: u for u in db.scalars(select(ProviderUsage).where(ProviderUsage.day == utcnow().date()))}
    states: dict[str, list[CatalogSyncState]] = {}
    for state in db.scalars(select(CatalogSyncState).order_by(CatalogSyncState.last_synced_at.desc().nulls_last())):
        states.setdefault(state.provider, []).append(state)
    out = []
    for p in known_providers():
        usage = today.get(p.key)
        out.append(AdminProviderOut(
            **_provider_out(p, counts),
            usage=ProviderUsageOut(requests_today=usage.requests if usage else 0,
                                   daily_quota=p.http.quota if hasattr(p, "http") else None,
                                   errors_today=usage.errors if usage else 0,
                                   last_error=usage.last_error if usage else None,
                                   last_error_at=usage.last_error_at if usage else None),
            sync=[SyncStateOut(language=s.language, next_offset=s.next_offset, exhausted=s.exhausted,
                               imported=s.imported, last_synced_at=s.last_synced_at, last_error=s.last_error)
                  for s in states.get(p.key, [])[:20]]))
    return out


@router.post("/admin/catalog/sync", response_model=FetchResultOut, tags=["admin"],
             summary="Fetch one or more pages of a language from providers now")
def admin_sync(data: SyncRequest, _: CatalogEditor, db: DB):
    lang = _get_language(db, data.language)
    imported = updated = 0
    statuses = []
    for _page in range(data.pages):
        result = federation.fetch_language(db, lang.code, providers=data.providers)
        imported, updated, statuses = imported + result.imported, updated + result.updated, result.statuses
        if not any(s.status == "ok" and s.count for s in result.statuses):
            break
    return FetchResultOut(language=lang.code, imported=imported, updated=updated, providers=_statuses(statuses))


@router.post("/admin/catalog/recheck", tags=["admin"],
             summary="Re-apply rights rules and screening to every stored provider track (no provider traffic)")
def admin_recheck(_: CatalogEditor, db: DB):
    checked, lost = recheck_rights(db)
    return {"checked": checked, "newly_unplayable": lost}


def _provider_song(db, song_id: uuid.UUID) -> Song:
    song = db.get(Song, song_id)
    if song is None:
        raise NotFound("Song not found")
    if song.is_local:
        raise AppError("This action applies to tracks from external providers", code="not_a_provider_track")
    return song


@router.post("/admin/songs/{song_id}/verify", response_model=SongOut, tags=["admin"],
             summary="Re-check a provider track's license and availability now")
def admin_verify(song_id: uuid.UUID, user: CatalogEditor, db: DB):
    song = _provider_song(db, song_id)
    federation.verify(db, song)
    return catalog_svc.song_outs(db, user, [song])[0]


@router.post("/admin/songs/{song_id}/takedown", response_model=SongOut, tags=["admin"])
def admin_takedown(song_id: uuid.UUID, data: TakedownRequest, user: CatalogEditor, db: DB):
    song = _provider_song(db, song_id)
    rights.takedown(db, song.source, song.provider_track_id, data.reason, f"admin:{user.id}")
    db.refresh(song)
    return catalog_svc.song_outs(db, user, [song])[0]


@router.delete("/admin/songs/{song_id}/takedown", response_model=SongOut, tags=["admin"],
               summary="Lift a takedown; the track is re-verified and only plays if still permitted")
def admin_restore(song_id: uuid.UUID, user: CatalogEditor, db: DB):
    song = _provider_song(db, song_id)
    rights.restore(db, song.source, song.provider_track_id)
    db.refresh(song)
    return catalog_svc.song_outs(db, user, [song])[0]


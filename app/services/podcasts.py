"""Podcast discovery, episodes and per-user state (follows, saved episodes, resume positions)."""

import math
import re
import unicodedata

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.models import EpisodeProgress, PodcastSubscription, SavedEpisode, User
from app.music import languages as langs
from app.music.federation import run_parallel
from app.music.http import ProviderError
from app.podcasts import providers as pp
from app.schemas.music import ProviderStatusOut
from app.schemas.podcast import EpisodeOut, EpisodeSnapshot, PodcastOut, ProgressIn


def _status(provider, result) -> ProviderStatusOut:
    if isinstance(result, ProviderError):
        kind = result.kind if result.kind in ("not_configured", "rate_limited", "quota_exceeded") else "error"
        return ProviderStatusOut(key=provider.key, name=provider.name, status=kind, count=0, message=result.message)
    if isinstance(result, TimeoutError):
        return ProviderStatusOut(key=provider.key, name=provider.name, status="timeout", count=0, message="Didn't answer in time")
    if isinstance(result, Exception):
        return ProviderStatusOut(key=provider.key, name=provider.name, status="error", count=0, message="Unexpected error")
    cnt = len(result) if isinstance(result, (list, tuple)) else (0 if result is None else 1)
    return ProviderStatusOut(key=provider.key, name=provider.name, status="ok", count=cnt, message=None)


def _norm(text: str | None) -> str:
    return re.sub(r"\W+", "", unicodedata.normalize("NFKC", text or "").casefold())


def _dedupe(podcasts: list[dict]) -> list[dict]:
    seen, out = set(), []
    for p in podcasts:
        keys = {("feed", _norm(p["feed_url"])) if p.get("feed_url") else None, ("title", _norm(p["title"]), _norm(p.get("publisher")))}
        keys.discard(None)
        if keys & seen:
            continue
        seen |= keys
        out.append(p)
    return out


def _finish(p: dict) -> dict:
    """Normalize the language to a catalog code or leave it unknown; never guess from the country."""
    p["language"] = langs.normalize(p.get("language")) if p.get("language") else None
    if p["language"] is None:
        p["language"] = langs.detect_from_script(p["title"], p.get("description"))
    return p


def search(
    q: str, *, country: str | None, language: str | None, category: str | None, provider: str | None, limit: int = 25
) -> tuple[list[dict], list[ProviderStatusOut]]:
    """Fan out to every configured podcast provider; one failing never fails the search."""
    term = q
    if language and language in langs.BY_CODE:
        term = f"{q} {langs.BY_CODE[language].name}".strip() if q else langs.BY_CODE[language].name + " podcast"
    selected = [p for p in pp.PROVIDERS.values() if (provider in (None, "", p.key))]
    calls = {}
    for p in selected:
        if not p.is_configured():
            continue
        if isinstance(p, pp.ITunesPodcasts):
            calls[p.key] = lambda p=p: p.search(term, country=country, category=category, limit=limit)
        elif isinstance(p, pp.PodcastIndex):
            calls[p.key] = lambda p=p: p.search(term, limit=limit) if q or language else p.trending(language=language, limit=limit)
        elif isinstance(p, pp.ListenNotes) and q:
            calls[p.key] = lambda p=p: p.search(q, language=language, limit=limit)
    results = run_parallel(calls, min(get_settings().music_search_budget_seconds, 2.5))

    statuses = [_status(p, results[p.key]) for p in selected if p.key in results]
    statuses += [
        ProviderStatusOut(key=p.key, name=p.name, status="not_configured", count=0, message="Needs an API key (see .env.example)")
        for p in selected
        if not p.is_configured()
    ]
    merged = [_finish(x) for p in selected if p.key in results and isinstance(results[p.key], list) for x in results[p.key]]
    merged = _dedupe(merged)
    if language:
        # Apple's search doesn't report a show's language, so read it from each unknown show's own RSS feed
        # (cached). Shows whose language still can't be determined are left out of a language-filtered view.
        _read_languages([p for p in merged if p["language"] is None and p.get("feed_url")][:15])
        merged = [p for p in merged if p["language"] == language]
    return merged, statuses


def _read_languages(podcasts: list[dict]) -> None:
    def read(p):
        return pp.fetch_feed(p["feed_url"], limit=1)[0].get("language")

    results = run_parallel({str(i): (lambda p=p: read(p)) for i, p in enumerate(podcasts)}, get_settings().music_search_budget_seconds)
    for i, p in enumerate(podcasts):
        value = results.get(str(i))
        if isinstance(value, str):
            p["language"] = langs.normalize(value)


def search_episodes(q: str, *, country: str | None, limit: int = 20) -> tuple[list[dict], list[ProviderStatusOut]]:
    results = run_parallel(
        {"itunes": lambda: pp.itunes.search_episodes(q, country=country, limit=limit)}, get_settings().music_search_budget_seconds
    )
    r = results["itunes"]
    return (r if isinstance(r, list) else []), [_status(pp.itunes, r)]


def resolve(podcast_id: str) -> tuple[dict, list[dict], list[ProviderStatusOut]]:
    """The podcast plus its episodes (newest first) as dicts."""
    provider, pid = pp.split_id(podcast_id)
    impl = pp.PROVIDERS.get(provider)
    if impl is None:
        raise NotFound("Unknown podcast source")
    statuses: list[ProviderStatusOut] = []
    try:
        if isinstance(impl, pp.ListenNotes):
            podcast, raw = impl.get(pid)
            episodes = raw
        else:
            podcast = impl.get(pid)
            if podcast is None:
                raise NotFound("Podcast not found")
            episodes = []
            if podcast.get("feed_url"):
                try:
                    meta, episodes = pp.fetch_feed(podcast["feed_url"])
                    for field in ("language", "website", "description", "publisher", "image_url"):
                        podcast[field] = podcast.get(field) or meta.get(field)
                    podcast["categories"] = podcast.get("categories") or meta.get("categories", [])
                    statuses.append(ProviderStatusOut(key="rss", name="Publisher RSS feed", status="ok", count=len(episodes), message=None))
                except ProviderError as exc:
                    statuses.append(ProviderStatusOut(key="rss", name="Publisher RSS feed", status="error", count=0, message=exc.message))
            if not episodes and provider == "podcastindex":
                episodes = impl.episodes(pid)
    except ProviderError as exc:
        if exc.kind == "not_found":
            raise NotFound("Podcast not found") from exc
        raise AppError(f"{impl.name} is unavailable right now: {exc.message}", code="provider_unavailable", status_code=502) from exc
    _finish(podcast)
    podcast.pop("_episodes_raw", None)
    eps = [pp.episode_dict(podcast, e) for e in episodes]
    eps.sort(key=lambda e: e["published_at"].timestamp() if e["published_at"] else 0, reverse=True)
    podcast["episode_count"] = podcast.get("episode_count") or len(eps) or None
    return podcast, eps, statuses


def paginate_episodes(episodes: list[dict], page: int, page_size: int, q: str | None = None) -> tuple[list[dict], int, int]:
    if q:
        needle = q.casefold()
        episodes = [e for e in episodes if needle in e["title"].casefold() or needle in (e.get("description") or "").casefold()]
    total = len(episodes)
    start = (page - 1) * page_size
    return episodes[start : start + page_size], total, max(1, math.ceil(total / page_size))


# --- per-user state --------------------------------------------------------------------------


def followed_ids(db: Session, user: User | None, ids: list[str] | None = None) -> set[str]:
    if not user:
        return set()
    stmt = select(PodcastSubscription.podcast_id).where(PodcastSubscription.user_id == user.id)
    if ids is not None:
        stmt = stmt.where(PodcastSubscription.podcast_id.in_(ids))
    return set(db.scalars(stmt))


def podcast_outs(db: Session, user: User | None, podcasts: list[dict]) -> list[PodcastOut]:
    followed = followed_ids(db, user, [p["id"] for p in podcasts]) if user else set()
    return [PodcastOut(**p, followed=(p["id"] in followed) if user else None) for p in podcasts]


def episode_outs(db: Session, user: User | None, episodes: list[dict]) -> list[EpisodeOut]:
    if not user or not episodes:
        return [EpisodeOut(**e) for e in episodes]
    ids = [e["id"] for e in episodes]
    saved = set(db.scalars(select(SavedEpisode.episode_id).where(SavedEpisode.user_id == user.id, SavedEpisode.episode_id.in_(ids))))
    progress = {
        p.episode_id: p
        for p in db.scalars(select(EpisodeProgress).where(EpisodeProgress.user_id == user.id, EpisodeProgress.episode_id.in_(ids)))
    }
    out = []
    for e in episodes:
        p = progress.get(e["id"])
        out.append(EpisodeOut(**e, saved=e["id"] in saved, position_s=p.position_s if p else None, completed=p.completed if p else None))
    return out


def follow(
    db: Session, user: User, podcast_id: str, title: str, publisher: str | None, image_url: str | None, language: str | None
) -> None:
    provider, _ = pp.split_id(podcast_id)
    if provider not in pp.PROVIDERS:
        raise NotFound("Unknown podcast source")
    db.execute(
        insert(PodcastSubscription)
        .values(
            user_id=user.id,
            podcast_id=podcast_id,
            provider=provider,
            title=title,
            publisher=publisher,
            image_url=image_url,
            language=language,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "podcast_id"],
            set_={"title": title, "publisher": publisher, "image_url": image_url, "language": language},
        )
    )
    db.commit()


def unfollow(db: Session, user: User, podcast_id: str) -> None:
    db.execute(delete(PodcastSubscription).where(PodcastSubscription.user_id == user.id, PodcastSubscription.podcast_id == podcast_id))
    db.commit()


def _check_episode(episode_id: str, snap: EpisodeSnapshot) -> str:
    provider, _ = pp.split_id(snap.podcast_id)
    if provider not in pp.PROVIDERS or not episode_id.startswith(f"{snap.podcast_id}#"):
        raise AppError("Episode id doesn't match its podcast", code="validation_error", status_code=422)
    if snap.audio_url and not snap.audio_url.startswith(("http://", "https://")):
        raise AppError("Audio URL must be http(s)", code="validation_error", status_code=422)
    return provider


def save_episode(db: Session, user: User, episode_id: str, snap: EpisodeSnapshot) -> None:
    provider = _check_episode(episode_id, snap)
    values = {
        "podcast_id": snap.podcast_id,
        "provider": provider,
        "title": snap.title,
        "podcast_title": snap.podcast_title,
        "image_url": snap.image_url,
        "audio_url": snap.audio_url,
        "duration_s": snap.duration_s,
        "published_at": snap.published_at,
        "description": snap.description,
    }
    db.execute(
        insert(SavedEpisode)
        .values(user_id=user.id, episode_id=episode_id, **values)
        .on_conflict_do_update(index_elements=["user_id", "episode_id"], set_=values)
    )
    db.commit()


def unsave_episode(db: Session, user: User, episode_id: str) -> None:
    db.execute(delete(SavedEpisode).where(SavedEpisode.user_id == user.id, SavedEpisode.episode_id == episode_id))
    db.commit()


def report_progress(db: Session, user: User, data: ProgressIn) -> None:
    provider = _check_episode(data.episode_id, data)
    values = {
        "podcast_id": data.podcast_id,
        "provider": provider,
        "title": data.title,
        "podcast_title": data.podcast_title,
        "image_url": data.image_url,
        "audio_url": data.audio_url,
        "position_s": data.position_s,
        "duration_s": data.duration_s,
        "completed": data.completed,
    }
    db.execute(
        insert(EpisodeProgress)
        .values(user_id=user.id, episode_id=data.episode_id, **values)
        .on_conflict_do_update(index_elements=["user_id", "episode_id"], set_={**values, "updated_at": func.now()})
    )
    db.commit()

"""Podcast discovery (iTunes, Podcast Index, Listen Notes), publisher-RSS episodes, and listening state."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, OptionalUser, PageParams
from app.core.rate_limit import rate_limit
from app.models import EpisodeProgress, PodcastSubscription, SavedEpisode
from app.podcasts import providers as pp
from app.schemas.common import Message, Page
from app.schemas.podcast import (
    CategoryOut,
    EpisodeOut,
    EpisodePageOut,
    EpisodeSnapshot,
    PodcastDetailOut,
    PodcastOut,
    PodcastSearchOut,
    ProgressIn,
    ProgressOut,
    SubscribeIn,
)
from app.services import podcasts as svc

router = APIRouter(tags=["podcasts"])
_fanout = Depends(rate_limit("podcast-fanout", limit=40, window=60))


@router.get("/podcasts/categories", response_model=list[CategoryOut], summary="Podcast categories (Apple Podcasts taxonomy)")
def categories():
    return [CategoryOut(id=i, name=n) for i, n in pp.CATEGORY_CHOICES]


@router.get(
    "/podcasts/search", response_model=PodcastSearchOut, dependencies=[_fanout], summary="Search podcasts across every configured provider"
)
def search_podcasts(
    db: DB,
    user: OptionalUser,
    q: Annotated[str, Query(max_length=100, description="Empty = discover by category / language")] = "",
    country: Annotated[str | None, Query(min_length=2, max_length=2, description="Apple Podcasts storefront, e.g. IN, US, JP")] = None,
    language: Annotated[str | None, Query(max_length=12)] = None,
    category: Annotated[str | None, Query(description="Category id from /podcasts/categories")] = None,
    provider: Annotated[str | None, Query(description="itunes | podcastindex | listennotes")] = None,
    limit: int = Query(25, ge=1, le=50),
):
    q = q.strip()
    names = dict(pp.CATEGORY_CHOICES)
    term = q or names.get(category or "") or ("" if language else "podcast")
    found, statuses = svc.search(term, country=country, language=language, category=category, provider=provider, limit=limit)
    basis = (
        "Matches for your search, in the providers' relevance order"
        if q
        else "Discovery results from the providers' search for this category/language - not a popularity ranking"
    )
    return PodcastSearchOut(query=q, basis=basis, podcasts=svc.podcast_outs(db, user, found), providers=statuses)


@router.get(
    "/podcasts/episodes/search",
    response_model=list[EpisodeOut],
    dependencies=[_fanout],
    summary="Search individual podcast episodes (Apple Podcasts)",
)
def search_episodes(
    db: DB,
    user: OptionalUser,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    country: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    limit: int = Query(20, ge=1, le=50),
):
    found, _ = svc.search_episodes(q.strip(), country=country, limit=limit)
    return svc.episode_outs(db, user, found)


@router.get(
    "/podcasts/{podcast_id}",
    response_model=PodcastDetailOut,
    dependencies=[_fanout],
    summary="One podcast (id = `<provider>:<id>`)",
)
def get_podcast(podcast_id: str, db: DB, user: OptionalUser):
    podcast, _, statuses = svc.resolve(podcast_id)
    out = svc.podcast_outs(db, user, [podcast])[0]
    return PodcastDetailOut(**out.model_dump(), providers=statuses)


@router.get(
    "/podcasts/{podcast_id}/episodes",
    response_model=EpisodePageOut,
    dependencies=[_fanout],
    summary="Episodes, newest first. Audio URLs are the publisher's own enclosures; nothing is copied.",
)
def podcast_episodes(podcast_id: str, db: DB, user: OptionalUser, page: PageParams, q: str | None = Query(None, max_length=100)):
    podcast, episodes, _ = svc.resolve(podcast_id)
    items, total, pages = svc.paginate_episodes(episodes, page.page, page.page_size, q)
    return EpisodePageOut(
        podcast=svc.podcast_outs(db, user, [podcast])[0],
        items=svc.episode_outs(db, user, items),
        total=total,
        page=page.page,
        page_size=page.page_size,
        pages=pages,
    )


# --- the signed-in listener's state -----------------------------------------------------------


@router.get("/me/podcasts", response_model=list[PodcastOut], summary="Podcasts I follow")
def my_podcasts(db: DB, user: CurrentUser):
    rows = db.scalars(
        select(PodcastSubscription).where(PodcastSubscription.user_id == user.id).order_by(PodcastSubscription.created_at.desc())
    ).all()
    return [
        PodcastOut(
            id=r.podcast_id,
            provider=r.provider,
            provider_id=r.podcast_id.partition(":")[2],
            title=r.title,
            publisher=r.publisher,
            image_url=r.image_url,
            language=r.language,
            followed=True,
        )
        for r in rows
    ]


@router.put("/me/podcasts/{podcast_id}", response_model=Message)
def follow_podcast(podcast_id: str, data: SubscribeIn, db: DB, user: CurrentUser):
    svc.follow(db, user, podcast_id, data.title, data.publisher, data.image_url, data.language)
    return Message(message="Following")


@router.delete("/me/podcasts/{podcast_id}", response_model=Message)
def unfollow_podcast(podcast_id: str, db: DB, user: CurrentUser):
    svc.unfollow(db, user, podcast_id)
    return Message(message="Unfollowed")


@router.get(
    "/me/podcasts/latest/episodes",
    response_model=list[EpisodeOut],
    summary="Newest episodes from followed podcasts (one feed fetch per show, cached)",
)
def latest_from_followed(db: DB, user: CurrentUser, per_show: int = Query(2, ge=1, le=5), limit: int = Query(20, ge=1, le=50)):
    from app.music.federation import run_parallel

    subs = db.scalars(
        select(PodcastSubscription).where(PodcastSubscription.user_id == user.id).order_by(PodcastSubscription.created_at.desc()).limit(15)
    ).all()
    results = run_parallel({s.podcast_id: (lambda pid=s.podcast_id: svc.resolve(pid)) for s in subs}, 12)
    episodes = []
    for value in results.values():
        if isinstance(value, tuple):
            episodes.extend(value[1][:per_show])
    episodes.sort(key=lambda e: e["published_at"].timestamp() if e["published_at"] else 0, reverse=True)
    return svc.episode_outs(db, user, episodes[:limit])


@router.get("/me/episodes", response_model=list[EpisodeOut], summary="Saved episodes")
def saved_episodes(db: DB, user: CurrentUser):
    rows = db.scalars(select(SavedEpisode).where(SavedEpisode.user_id == user.id).order_by(SavedEpisode.created_at.desc())).all()
    progress = {p.episode_id: p for p in db.scalars(select(EpisodeProgress).where(EpisodeProgress.user_id == user.id))}
    return [
        EpisodeOut(
            id=r.episode_id,
            podcast_id=r.podcast_id,
            provider=r.provider,
            podcast_title=r.podcast_title,
            title=r.title,
            description=r.description,
            audio_url=r.audio_url,
            duration_s=r.duration_s,
            published_at=r.published_at,
            image_url=r.image_url,
            playable=bool(r.audio_url),
            saved=True,
            position_s=progress[r.episode_id].position_s if r.episode_id in progress else None,
            completed=progress[r.episode_id].completed if r.episode_id in progress else None,
        )
        for r in rows
    ]


@router.put("/me/episodes/save", response_model=Message)
def save_episode(episode_id: Annotated[str, Query(max_length=160)], data: EpisodeSnapshot, db: DB, user: CurrentUser):
    svc.save_episode(db, user, episode_id, data)
    return Message(message="Episode saved")


@router.delete("/me/episodes/save", response_model=Message)
def unsave_episode(episode_id: Annotated[str, Query(max_length=160)], db: DB, user: CurrentUser):
    svc.unsave_episode(db, user, episode_id)
    return Message(message="Episode removed")


@router.put("/me/episodes/progress", response_model=Message, summary="Report playback position (resume + listening history)")
def report_progress(data: ProgressIn, db: DB, user: CurrentUser):
    svc.report_progress(db, user, data)
    return Message(message="Saved")


@router.get("/me/episodes/progress", response_model=Page[ProgressOut], summary="Podcast listening history, most recent first")
def listening_history(db: DB, user: CurrentUser, page: PageParams):
    from sqlalchemy import func

    base = select(EpisodeProgress).where(EpisodeProgress.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(EpisodeProgress.updated_at.desc()).offset(page.offset).limit(page.page_size)).all()
    return Page.build([ProgressOut.model_validate(r, from_attributes=True) for r in rows], total, page.page, page.page_size)

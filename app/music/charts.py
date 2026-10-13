"""Charts built only from data we actually have.

Score = listens on this server in the last 7 days + 5 × the provider's own popularity signal (0..1).
Local listening dominates once people use the app; until then the providers' rankings carry the chart.
A region chart includes tracks whose release country is in the region, or (when the country is unknown)
whose language's primary region is that region.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.security import utcnow
from app.models import Language, ListeningHistory, Song
from app.music import languages as langs
from app.repositories.catalog import playable_condition

BASIS = ("Ranked by listens on this server over the last 7 days, then by each source's own popularity signal. "
         "Only tracks we're authorized to play are included.")

# ISO 3166-1 alpha-2 country -> chart region (same keys as languages.REGIONS).
_REGION_COUNTRIES = {
    "south-asia": "IN PK BD LK NP BT MV AF",
    "east-asia": "CN JP KR KP TW HK MO MN",
    "southeast-asia": "ID MY SG TH VN PH MM KH LA BN TL",
    "central-asia": "KZ UZ TM KG TJ GE AM AZ",
    "middle-east": "SA AE QA KW BH OM YE IQ IR SY JO LB IL PS TR EG LY TN DZ MA SD",
    "africa": ("NG GH KE ZA ET TZ UG RW BI CD CG CM CI SN ML BF NE TD CF GA GQ AO ZM ZW MW MZ MG BW NA "
               "LS SZ SO DJ ER SS LR SL GN GW GM BJ TG CV ST MU SC KM"),
    "europe": ("GB IE FR DE NL BE LU CH AT IT ES PT AD MC SM VA MT GR CY SE NO DK FI IS EE LV LT PL CZ SK HU "
               "SI HR BA RS ME MK AL XK BG RO MD UA BY RU"),
    "latin-america": ("MX GT BZ SV HN NI CR PA CU DO HT JM TT BB BS LC VC GD AG DM KN PR CO VE EC PE BO CL AR "
                      "UY PY BR GY SR"),
    "north-america": "US CA GL",
    "oceania": "AU NZ PG FJ SB VU WS TO KI TV NR PW FM MH",
}
REGION_COUNTRIES = {region: tuple(codes.split()) for region, codes in _REGION_COUNTRIES.items()}


@dataclass
class ChartInfo:
    id: str
    kind: str  # global | region | language
    title: str
    subtitle: str
    track_count: int


def _region_filter(region: str):
    codes = [lang.code for lang in langs.LANGUAGES if lang.region == region]
    countries = REGION_COUNTRIES.get(region, ())
    return or_(Song.country.in_(countries), and_(Song.country.is_(None), Song.language.in_(codes)))


def _filter_for(chart_id: str):
    kind, _, value = chart_id.partition(":")
    if chart_id == "global":
        return None
    if kind == "region" and value in langs.REGIONS and value != "global":
        return _region_filter(value)
    if kind == "language" and value in langs.BY_CODE:
        return Song.language == value
    raise NotFound("Unknown chart")


def list_charts(db: Session) -> list[ChartInfo]:
    total = db.scalar(select(func.count()).select_from(Song).where(playable_condition())) or 0
    charts = [ChartInfo("global", "global", "Global Top 50", "Across every language and source", total)]
    for region, label in langs.REGIONS.items():
        if region == "global":
            continue
        n = db.scalar(select(func.count()).select_from(Song).where(playable_condition(), _region_filter(region))) or 0
        if n:
            charts.append(ChartInfo(f"region:{region}", "region", f"Top 50 · {label}", label, n))
    rows = db.execute(select(Language, func.count(Song.id)).join(Song, Song.language == Language.code)
                      .where(playable_condition()).group_by(Language.code)
                      .order_by(Language.featured_rank.nulls_last(), func.count(Song.id).desc())).all()
    for lang, n in rows:
        charts.append(ChartInfo(f"language:{lang.code}", "language", f"Top 50 · {lang.name}", lang.native_name, n))
    return charts


def chart_title(chart_id: str) -> str:
    kind, _, value = chart_id.partition(":")
    if kind == "region":
        return f"Top 50 · {langs.REGIONS[value]}"
    if kind == "language":
        return f"Top 50 · {langs.BY_CODE[value].name}"
    return "Global Top 50"


def chart_tracks(db: Session, chart_id: str, limit: int = 50) -> list[tuple[Song, int]]:
    """(song, listens in the last 7 days), best first."""
    condition = _filter_for(chart_id)
    plays = (select(ListeningHistory.song_id, func.count().label("n"))
             .where(ListeningHistory.played_at >= utcnow() - timedelta(days=7))
             .group_by(ListeningHistory.song_id).subquery())
    listens = func.coalesce(plays.c.n, 0)
    score = listens + 5 * func.coalesce(Song.provider_popularity, 0)
    stmt = (select(Song, listens).outerjoin(plays, plays.c.song_id == Song.id).where(playable_condition())
            .order_by(score.desc(), Song.play_count.desc(), Song.id).limit(limit))
    if condition is not None:
        stmt = stmt.where(condition)
    return [(song, int(n)) for song, n in db.execute(stmt).unique().all()]

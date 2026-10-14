"""Movie soundtrack discovery from iTunes (albums, previews) and MusicBrainz (release language/country/date).

Everything returned comes from provider responses. Fields a provider doesn't state stay null (shown as
Unknown); nothing is inferred from the search text, and the "composer" is reported only as the album's
credited lead artist because neither source marks composers explicitly.
"""

import re
from datetime import date

from app.music import languages as langs
from app.music.federation import run_parallel
from app.music.http import ProviderError
from app.music.providers import get_provider, is_enabled
from app.music.providers.itunes import LANGUAGE_STORES, track_language
from app.music.providers.musicbrainz import MusicBrainzProvider

_SOUNDTRACK = re.compile(
    r"soundtrack|original (?:motion picture|score|film|series|cast)|\bo\.?s\.?t\b|from the (?:motion picture|film|movie)|"
    r"from [\"“]",
    re.I,
)
# "Title (Original Motion Picture Soundtrack)" / 'Song (From "Movie")' / "Title - OST"
_STRIP = re.compile(
    r"\s*[\(\[][^\)\]]*(?:soundtrack|original|ost|score|motion picture|deluxe|edition)[^\)\]]*[\)\]]|"
    r"\s*[-–]\s*(?:single|ep|ost|soundtrack).*$|\s+(?:ost|o\.s\.t\.?)\b.*$",
    re.I,
)
_FROM = re.compile(r"[\(\[-]\s*from (?:the (?:motion picture|film|movie)\s*)?[\"“]([^\"”]+)[\"”]", re.I)


def movie_title(album_title: str) -> str:
    """The film a soundtrack album belongs to: a `(From "X")` credit if present, else the title minus 'Soundtrack' tags."""
    m = _FROM.search(album_title)
    if m:
        return m.group(1).strip()
    title = album_title
    for _ in range(3):  # several tags may stack: "X (Original Motion Picture Soundtrack) [Telugu] - EP"
        title = _STRIP.sub("", title).strip()
    title = re.sub(r"\s*\[[^\]]*\]\s*$", "", title).strip()
    return title or album_title


def _year(value: str | None) -> tuple[date | None, int | None]:
    if not value:
        return None, None
    try:
        d = date.fromisoformat(value[:10])
        return d, d.year
    except ValueError:
        return None, int(value[:4]) if value[:4].isdigit() else None


def _from_itunes(r: dict, access: str = "preview") -> dict:
    d, year = _year(r.get("releaseDate"))
    artwork = (r.get("artworkUrl100") or "").replace("100x100bb", "600x600bb") or None
    title = r.get("collectionName") or ""
    return {
        "id": f"itunes:{r['collectionId']}",
        "provider": "itunes",
        "movie_title": movie_title(title),
        "album_title": title,
        "credited_artist": r.get("artistName"),
        "release_date": d,
        "release_year": year,
        "language": track_language(r.get("primaryGenreName")) or langs.detect_from_script(title, r.get("artistName")),
        "language_source": "provider",
        "country": None,
        "genre": r.get("primaryGenreName"),
        "track_count": r.get("trackCount"),
        "artwork_url": artwork,
        "source_url": r.get("collectionViewUrl"),
        "access": access,
    }


def _from_musicbrainz(r: dict) -> dict:
    d, year = _year(r.get("date"))
    return {
        "id": f"musicbrainz:{r['id']}",
        "provider": "musicbrainz",
        "movie_title": movie_title(r["title"]),
        "album_title": r["title"],
        "credited_artist": r.get("artist"),
        "release_date": d,
        "release_year": year,
        "language": r.get("language"),
        "language_source": "musicbrainz" if r.get("language") else None,
        "country": r.get("country"),
        "genre": None,
        "track_count": r.get("track_count"),
        "artwork_url": None,
        "source_url": r["url"],
        "access": "metadata",
    }


def _norm(text: str) -> str:
    return re.sub(r"\W+", "", text.casefold())


def search(
    q: str, *, language: str | None, country: str | None, year_from: int | None, year_to: int | None, limit: int = 24
) -> tuple[list[dict], list]:
    from app.services.podcasts import _status  # same status shape as the other fan-outs

    itunes = get_provider("itunes")
    mb = get_provider("musicbrainz")
    calls = {}
    lang_name = langs.BY_CODE[language].name if language in langs.BY_CODE else ""
    term = " ".join(x for x in (q, lang_name, "movie soundtrack") if x).strip()
    store = LANGUAGE_STORES.get(language or "") or country
    if itunes and is_enabled(itunes):

        def run_itunes():
            found = itunes.search_albums(term, country=store, limit=50)
            if not found and store:  # some storefronts return nothing for a term; the default one often does not
                found = itunes.search_albums(term, limit=50)
            return found

        calls["itunes"] = run_itunes
    if mb and is_enabled(mb) and isinstance(mb, MusicBrainzProvider):
        calls["musicbrainz"] = lambda: mb.search_soundtracks(
            q, language=language, country=country, year_from=year_from, year_to=year_to, limit=20
        )
    from app.core.config import get_settings

    results = run_parallel(calls, min(get_settings().music_search_budget_seconds, 2.5))

    statuses, items = [], []
    for key, value in results.items():
        provider = get_provider(key)
        if isinstance(value, list):
            raw = value
            if key == "itunes":
                raw = [r for r in value if _SOUNDTRACK.search(r.get("collectionName") or "") or r.get("primaryGenreName") == "Soundtrack"]
                rows = [_from_itunes(r) for r in raw]
            else:
                rows = [_from_musicbrainz(r) for r in raw]
            from app.schemas.music import ProviderStatusOut

            statuses.append(ProviderStatusOut(key=key, name=provider.name, status="ok", count=len(rows), message=None))
            items.extend(rows)
        else:
            statuses.append(_status(provider, value))

    def keep(row: dict) -> bool:
        if language and row["language"] != language:
            return False
        if country and row["country"] and row["country"] != country:
            return False
        y = row["release_year"]
        if year_from and (y is None or y < year_from):
            return False
        return not (year_to and (y is None or y > year_to))

    items = [r for r in items if keep(r)]
    seen, unique = set(), []
    for row in sorted(items, key=lambda r: (r["provider"] != "itunes", -(r["release_year"] or 0))):  # iTunes first: has audio previews
        key = (_norm(row["movie_title"]), _norm(row["credited_artist"] or ""), row["release_year"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique[:limit], statuses


def group_by_movie(rows: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for row in rows:
        g = groups.setdefault(
            _norm(row["movie_title"]),
            {
                "title": row["movie_title"],
                "release_year": row["release_year"],
                "language": row["language"],
                "country": row["country"],
                "artwork_url": row["artwork_url"],
                "soundtracks": [],
            },
        )
        g["soundtracks"].append(row)
        g["artwork_url"] = g["artwork_url"] or row["artwork_url"]
        g["country"] = g["country"] or row["country"]
        g["language"] = g["language"] or row["language"]
    return list(groups.values())


def detail(soundtrack_id: str):
    """The album with its track list. iTunes tracks are added to the catalog so they can be played (as previews)."""
    provider, _, pid = soundtrack_id.partition(":")
    if provider == "itunes":
        itunes = get_provider("itunes")
        if itunes is None or not is_enabled(itunes):
            raise ProviderError("itunes", "not_configured", "iTunes is disabled on this server")
        album, tracks = itunes.lookup_album(pid)
        if album is None:
            raise ProviderError("itunes", "not_found", "Album not found")
        return _from_itunes(album), tracks
    if provider == "musicbrainz":
        mb = get_provider("musicbrainz")
        if mb is None or not is_enabled(mb) or not isinstance(mb, MusicBrainzProvider):
            raise ProviderError("musicbrainz", "not_configured", "MusicBrainz is disabled on this server")
        rel = mb.release_tracks(pid)
        row = _from_musicbrainz({**rel, "track_count": len(rel["tracks"])})
        return row, rel["tracks"]
    raise ProviderError("soundtracks", "bad_response", "Unknown soundtrack source")

"""Fill in artists' countries from MusicBrainz so the catalog can be browsed by country.

    uv run python -m scripts.enrich_countries [--limit 300]

Artists with the most playable tracks come first. A country is only recorded when MusicBrainz has an exact
(normalized) name match with a top score and lists a country for it; anything else stays Unknown. MusicBrainz allows
one request per second, so this takes about a second per artist. Safe to re-run.
"""

import argparse
import logging
import time

from sqlalchemy import func, select

from app.core.security import utcnow
from app.db.session import SessionLocal
from app.models import Artist, Song
from app.music.http import ProviderError
from app.music.providers import get_provider, is_enabled
from app.repositories.catalog import playable_condition

logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=300)
    args = parser.parse_args()
    mb = get_provider("musicbrainz")
    if mb is None or not is_enabled(mb):
        raise SystemExit("MusicBrainz is not enabled (MUSIC_PROVIDERS)")
    found = checked = 0
    with SessionLocal() as db:
        playable = func.count().filter(playable_condition())
        rows = db.execute(
            select(Artist.id, Artist.name).join(Song, Song.artist_id == Artist.id)
            .where(Artist.country.is_(None), Artist.country_checked_at.is_(None), Artist.source != "local")
            .group_by(Artist.id).order_by(playable.desc()).limit(args.limit)
        ).all()
        for artist_id, name in rows:
            checked += 1
            try:
                match = mb.artist_country(name)
            except ProviderError as exc:
                if exc.kind == "quota_exceeded":
                    print(f"stopping: {exc.message}")
                    break
                if exc.kind in ("rate_limited", "unavailable"):
                    time.sleep(30)  # MusicBrainz asked us to slow down: wait, then move on to the next artist
                continue
            artist = db.get(Artist, artist_id)
            artist.country_checked_at = utcnow()  # whether or not a country was found, don't ask again
            if match:
                artist.musicbrainz_id, artist.country = match
                found += 1
            if checked % 25 == 0:
                db.commit()
                print(f"{checked}/{len(rows)} checked, {found} countries found", flush=True)
        db.commit()
    print(f"done: {found} of {checked} artists got a country")


if __name__ == "__main__":
    main()

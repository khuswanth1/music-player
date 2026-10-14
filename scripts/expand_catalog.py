"""Widen the catalog: pull pages of every canonical genre and every featured language from the music providers.

    uv run python -m scripts.expand_catalog [--genre-pages 2] [--language-pages 1] [--only jazz,te]

Everything comes from provider APIs under their own rate limits and daily quotas (a provider that runs out simply
reports it); nothing is downloaded or stored besides metadata and the provider's own stream URL. Safe to re-run.
"""

import argparse
import logging

from app.db.session import SessionLocal
from app.models import Language
from app.music import federation
from app.music.genres import CANONICAL

logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--genre-pages", type=int, default=2)
    parser.add_argument("--language-pages", type=int, default=1)
    parser.add_argument("--only", default="", help="comma-separated genre names/slugs or language codes")
    args = parser.parse_args()
    only = {x.strip().lower() for x in args.only.split(",") if x.strip()}
    total = 0
    with SessionLocal() as db:
        for name in CANONICAL:
            if only and name.lower() not in only and name.lower().replace(" ", "-") not in only:
                continue
            for page in range(args.genre_pages):
                result = federation.fetch_genre(db, name, page=page, budget=25)
                total += result.imported
                bad = {s.key: s.status for s in result.statuses if s.status not in ("ok", "not_configured", "disabled")}
                print(f"genre {name:<20} page {page}: +{result.imported:<3} {bad or ''}", flush=True)
        codes = [row for row in db.query(Language.code).filter(Language.featured_rank.is_not(None)).order_by(Language.featured_rank)]
        for (code,) in codes:
            if only and code not in only:
                continue
            for _ in range(args.language_pages):
                result = federation.fetch_language(db, code, budget=25)
                total += result.imported
                print(f"language {code:<6}: +{result.imported}", flush=True)
    print(f"done: {total} new tracks")


if __name__ == "__main__":
    main()

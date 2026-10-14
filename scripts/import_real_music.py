# ruff: noqa: E402  (the backend root has to be on sys.path before the app imports)
import sys
from pathlib import Path

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Album
from app.music.ingest import ingest
from app.music.providers.audius import AudiusProvider

GENRES_TO_FETCH = ["Pop", "Electronic", "Hip-Hop", "Lo-Fi", "Rock", "House", "Ambient"]

def main():
    print("=" * 60)
    print("Fetching and importing REAL music from Audius...")
    print("=" * 60)

    provider = AudiusProvider()
    all_tracks = []
    seen_ids = set()

    # 1. Fetch top monthly trending tracks
    print("-> Fetching general trending tracks...")
    try:
        trending = provider.browse(limit=30)
        for t in trending:
            if t.provider_track_id not in seen_ids:
                seen_ids.add(t.provider_track_id)
                all_tracks.append(t)
        print(f"   Fetched {len(trending)} trending tracks.")
    except Exception as e:
        print(f"   Error fetching trending: {e}")

    # 2. Fetch tracks across various popular genres
    for genre in GENRES_TO_FETCH:
        print(f"-> Fetching top {genre} tracks...")
        try:
            genre_tracks = provider.browse(genre=genre, limit=10)
            added = 0
            for t in genre_tracks:
                if t.provider_track_id not in seen_ids:
                    seen_ids.add(t.provider_track_id)
                    all_tracks.append(t)
                    added += 1
            print(f"   Added {added} tracks for {genre}.")
        except Exception as e:
            print(f"   Error fetching {genre}: {e}")

    print(f"\nTotal unique real tracks to ingest: {len(all_tracks)}")

    # 3. Ingest into database
    with SessionLocal() as db:
        print("-> Ingesting songs, artists, albums, and streaming URLs into PostgreSQL...")
        result = ingest(db, all_tracks)
        db.commit()

        print(f"   Ingest finished: {result.created} created, {result.updated} updated.")

        # 4. Feature a few albums with covers on the Home Page
        print("-> Featuring imported albums on the Home Page...")
        
        # Mark up to 8 albums with covers as featured
        albums = db.scalars(
            select(Album)
            .where(Album.source == "audius", Album.cover_url.is_not(None))
            .limit(8)
        ).all()
        for alb in albums:
            alb.is_featured = True
        
        # play_count is only ever raised by real listens here; the provider's own ordering is kept in
        # provider_popularity by the Audius adapter, so nothing is invented.
        db.commit()
        print(f"   Featured {len(albums)} real albums.")

    print("\n" + "=" * 60)
    print("SUCCESS: Real music is now in your library and on the Home Page!")
    print("Visit http://localhost:5173/ to listen and play real songs.")
    print("=" * 60)

if __name__ == "__main__":
    main()

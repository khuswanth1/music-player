import sys
from pathlib import Path
import httpx

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import select, update
from app.db.session import SessionLocal
from app.music.providers.audius import AudiusProvider
from app.music.ingest import ingest
from app.models import Album, Song

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

        # 4. Feature top albums and boost real song play counts so they appear on HomePage
        print("-> Promoting imported real tracks to Home Page Featured & Trending...")
        
        # Mark up to 8 albums with covers as featured
        albums = db.scalars(
            select(Album)
            .where(Album.source == "audius", Album.cover_url.is_not(None))
            .limit(8)
        ).all()
        for idx, alb in enumerate(albums):
            alb.is_featured = True
        
        # Give imported songs realistic play counts so they top Trending and Recommendations
        audius_songs = db.scalars(
            select(Song)
            .where(Song.source == "audius")
        ).all()
        
        for idx, s in enumerate(audius_songs):
            s.play_count = 5000 - (idx * 50)  # Decreasing play counts for realistic rank
        
        db.commit()
        print(f"   Featured {len(albums)} real albums.")
        print(f"   Ranked {len(audius_songs)} real songs on Trending & Home Page.")

    print("\n" + "=" * 60)
    print("SUCCESS: Real music is now in your library and on the Home Page!")
    print("Visit http://localhost:5173/ to listen and play real songs.")
    print("=" * 60)

if __name__ == "__main__":
    main()

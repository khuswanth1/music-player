"""Seed the database with an original demo catalog and demo accounts.

    uv run python -m scripts.seed            # seed once (skips if already seeded)
    uv run python -m scripts.seed --reset    # wipe all data first (development only)

All audio and artwork is generated procedurally by scripts/synth.py (original, CC0).
Every artist, album and track name is fictional.
Demo account passwords come from SEED_DEMO_PASSWORD (see .env.example).
"""

import argparse
import io
import os
import random
import shutil
import sys
import uuid
from datetime import date, timedelta

from sqlalchemy import select, text, update

from app.billing.plans import PLANS
from app.core.config import get_settings
from app.core.permissions import ROLE_IDS, RoleName
from app.core.security import generate_invite_code, hash_password, utcnow
from app.db.session import SessionLocal, engine
from app.models import (
    Album,
    AlbumType,
    Artist,
    FollowedArtist,
    Genre,
    LikedSong,
    ListeningHistory,
    Payment,
    PaymentStatus,
    Plan,
    Playlist,
    PlaylistCollaborator,
    PlaylistTrack,
    SavedAlbum,
    Song,
    Subscription,
    SubscriptionStatus,
    User,
)
from app.services.catalog import slugify
from app.storage.backends import LocalStorage, get_storage, media_url
from scripts.synth import SR, avatar_svg, cover_svg, encode_ogg, render

GENRES = [  # name, style, color
    ("Lo-Fi", "lofi", "#c084fc"), ("Synthwave", "synthwave", "#f472b6"), ("Ambient", "ambient", "#38bdf8"),
    ("Chiptune", "chiptune", "#facc15"), ("House", "house", "#34d399"), ("Downtempo", "downtempo", "#fb923c"),
]

PALETTES = {
    "lofi": ("#4c1d95", "#1e1b4b", "#c4b5fd"), "synthwave": ("#be185d", "#1e1b4b", "#fbbf24"),
    "ambient": ("#0c4a6e", "#082f49", "#7dd3fc"), "chiptune": ("#854d0e", "#1c1917", "#fde047"),
    "house": ("#065f46", "#022c22", "#6ee7b7"), "downtempo": ("#9a3412", "#292524", "#fdba74"),
}
MOTIFS = {"lofi": "orbs", "synthwave": "sun", "ambient": "waves", "chiptune": "grid", "house": "orbs", "downtempo": "waves"}

# artist, style, bio, albums: (title, type, release, featured, [(track, premium)])
CATALOG = [
    ("Velvet Static", "lofi", "Bedroom producer making rainy-window beats with dusty keys and soft swing.", [
        ("Rain on the Window", AlbumType.album, date(2026, 3, 6), True,
         [("Kettle Steam", False), ("Late Bus Home", False), ("Notebook Margins", False), ("Window Seat", False)]),
        ("Pocket Tapes", AlbumType.ep, date(2025, 11, 14), False, [("Cassette Warmth", False), ("Lamp Light", False)]),
    ]),
    ("Midnight Arcade", "synthwave", "Neon-soaked synth duo scoring drives that never end.", [
        ("Neon Coastline", AlbumType.album, date(2026, 8, 21), True,
         [("Chrome Horizon", False), ("Overdrive Sunset", False), ("Grid Runner", False), ("Afterglow Highway", True)]),
    ]),
    ("Glass Harbor", "ambient", "Slow-moving textures for focus, sleep and long train rides.", [
        ("Tidelines", AlbumType.album, date(2026, 1, 30), False,
         [("First Light", False), ("Salt Air", False), ("Drift Ice", False)]),
        ("Lantern", AlbumType.single, date(2026, 9, 12), True, [("Lantern", True)]),
    ]),
    ("Pixel Pilot", "chiptune", "8-bit adventurer turning boss fights into earworms.", [
        ("Level Select", AlbumType.album, date(2025, 9, 5), False,
         [("Press Start", False), ("Coin Rush", False), ("Warp Zone", False), ("Final Boss", False)]),
    ]),
    ("Tidal Room", "house", "Warm club grooves built for sunrise sets.", [
        ("Open Floor", AlbumType.ep, date(2026, 6, 19), True,
         [("Sunrise Set", False), ("Basement Steps", False), ("Second Wind", True)]),
        ("Heat Map", AlbumType.single, date(2026, 10, 2), False, [("Heat Map", False)]),
    ]),
    ("Paper Lanterns", "downtempo", "Hazy downtempo with bells, brushes and late-evening calm.", [
        ("Slow Signals", AlbumType.album, date(2026, 4, 24), False,
         [("Porch Light", False), ("Static Bloom", False), ("Night Ferry", False)]),
    ]),
]

DEMO_USERS = [  # email, display name, role, premium
    ("admin@wavely.dev", "Ada Admin", RoleName.admin, True),
    ("curator@wavely.dev", "Cleo Curator", RoleName.content_manager, False),
    ("listener@wavely.dev", "Leo Listener", RoleName.listener, False),
    ("premium@wavely.dev", "Priya Premium", RoleName.listener, True),
]
EXTRA_LISTENERS = ["Mika", "Jonah", "Sasha", "Ravi", "Noor", "Tess", "Omar", "Yuki"]


def _save(storage, key: str, data: bytes, content_type: str) -> None:
    storage.save(key, io.BytesIO(data), content_type)


def reset() -> None:
    if get_settings().environment == "production":
        sys.exit("Refusing to reset a production database.")
    with engine.begin() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('roles','languages','alembic_version')"))]
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    storage = get_storage()
    if isinstance(storage, LocalStorage):  # S3 objects are left alone; clean buckets deliberately
        for sub in ("audio", "images"):
            shutil.rmtree(storage.root / sub, ignore_errors=True)
    print("Database and local media cleared.")


def seed() -> None:
    settings = get_settings()
    password = os.environ.get("SEED_DEMO_PASSWORD") or _dotenv("SEED_DEMO_PASSWORD")
    if not password:
        sys.exit("Set SEED_DEMO_PASSWORD (see .env.example) to create the demo accounts.")
    if settings.environment == "production":
        sys.exit("Demo data is for development and staging only.")

    storage = get_storage()
    rng = random.Random(42)
    with SessionLocal() as db:
        if db.scalar(select(Artist).where(Artist.slug == "velvet-static")):
            print("Already seeded. Use --reset to start over.")
            return

        print("Creating genres, artists, albums and tracks (audio is synthesized, ~0.5 s per track)...")
        genres = {}
        for name, style, color in GENRES:
            genres[style] = Genre(name=name, slug=slugify(name), color=color)
            db.add(genres[style])
        db.flush()

        songs: list[Song] = []
        seed_n = 100
        for artist_name, style, bio, albums in CATALOG:
            palette = PALETTES[style]
            image_key = f"images/artists/{uuid.uuid4().hex}.svg"
            _save(storage, image_key, avatar_svg(artist_name, palette).encode(), "image/svg+xml")
            artist = Artist(name=artist_name, slug=slugify(artist_name), bio=bio, verified=True,
                            image_url=media_url(image_key))
            db.add(artist)
            db.flush()
            for title, album_type, released, featured, tracks in albums:
                seed_n += 1
                cover_key = f"images/covers/{uuid.uuid4().hex}.svg"
                _save(storage, cover_key, cover_svg(title, palette, MOTIFS[style], seed_n).encode(), "image/svg+xml")
                album = Album(title=title, artist_id=artist.id, album_type=album_type, release_date=released,
                              is_featured=featured, cover_url=media_url(cover_key))
                db.add(album)
                db.flush()
                for number, (track, premium) in enumerate(tracks, 1):
                    seed_n += 1
                    seconds = rng.uniform(32, 48)
                    samples = render(style, seed_n, seconds)
                    data = encode_ogg(samples)
                    key = f"audio/{uuid.uuid4().hex}.ogg"
                    _save(storage, key, data, "audio/ogg")
                    song = Song(title=track, artist_id=artist.id, album_id=album.id, genre_id=genres[style].id,
                                track_number=number, duration_ms=round(len(samples) / SR * 1000), audio_key=key,
                                audio_mime="audio/ogg", audio_size=len(data), is_premium=premium,
                                # Procedurally generated here, so: instrumental, CC0, attribution not required.
                                language="zxx", language_source="manual", license_code="cc0",
                                license_name="CC0 1.0", license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                                attribution=f'"{track}" by {artist_name} (CC0 1.0), generated for the Wavely demo.')
                    db.add(song)
                    songs.append(song)
                    print(f"  {artist_name} - {track}")
        db.flush()

        print("Creating demo accounts...")
        pw_hash = hash_password(password)
        users: dict[str, User] = {}
        now = utcnow()
        for email, name, role, premium in DEMO_USERS:
            user = User(email=email, display_name=name, password_hash=pw_hash, role_id=ROLE_IDS[role])
            db.add(user)
            db.flush()
            users[email] = user
            if premium:
                sub = Subscription(user_id=user.id, plan=Plan.premium_monthly, status=SubscriptionStatus.active,
                                   provider="manual", current_period_start=now - timedelta(days=12),
                                   current_period_end=now + timedelta(days=18))
                db.add(sub)
                db.flush()
                plan = PLANS[Plan.premium_monthly]
                db.add(Payment(user_id=user.id, subscription_id=sub.id, provider="manual",
                               provider_payment_id=f"seed_{uuid.uuid4().hex[:16]}", amount_cents=plan.amount_cents,
                               currency=plan.currency, status=PaymentStatus.succeeded,
                               description=f"{plan.name} (seed data)"))
        extras = []
        for name in EXTRA_LISTENERS:
            user = User(email=f"{name.lower()}@example.com", display_name=name, password_hash=pw_hash,
                        role_id=ROLE_IDS[RoleName.listener])
            db.add(user)
            extras.append(user)
        db.flush()
        # spread sign-up dates so the analytics chart has shape
        for i, user in enumerate(extras):
            db.execute(update(User).where(User.id == user.id).values(created_at=now - timedelta(days=3 + i * 3)))

        print("Creating playlists, likes, follows and listening history...")
        listener, premium_user, curator = users["listener@wavely.dev"], users["premium@wavely.dev"], users["curator@wavely.dev"]

        def playlist(owner: User, name: str, description: str, picks: list[Song], *, public=True, collaborative=False):
            pl = Playlist(owner_id=owner.id, name=name, description=description, is_public=public and not collaborative,
                          is_collaborative=collaborative, collab_invite_code=generate_invite_code() if collaborative else None)
            db.add(pl)
            db.flush()
            for pos, song in enumerate(picks):
                db.add(PlaylistTrack(playlist_id=pl.id, song_id=song.id, position=pos, added_by_id=owner.id))
            return pl

        by_style = {style: [s for s in songs if s.genre_id == genres[style].id] for _, style, _ in GENRES}
        playlist(curator, "Wavely Picks", "Hand-picked favourites from across the catalog.",
                 rng.sample(songs, 10))
        playlist(curator, "Deep Focus", "Ambient and lo-fi for heads-down work.",
                 by_style["ambient"] + by_style["lofi"][:4])
        playlist(listener, "Late Night Drive", "Synths and city lights.", by_style["synthwave"] + by_style["downtempo"])
        playlist(listener, "Gym Mix", "Private warm-up list.", by_style["house"] + by_style["chiptune"][:2], public=False)
        jam = playlist(premium_user, "Weekend Jam", "Collaborative — everyone adds a track.",
                       [by_style["house"][0], by_style["lofi"][1]], collaborative=True)
        db.add(PlaylistCollaborator(playlist_id=jam.id, user_id=listener.id))

        for user, liked in ((listener, rng.sample(songs, 8)), (premium_user, rng.sample(songs, 12))):
            for song in liked:
                db.add(LikedSong(user_id=user.id, song_id=song.id))
        artists = db.scalars(select(Artist)).all()
        for user in (listener, premium_user):
            for artist in rng.sample(list(artists), 3):
                db.add(FollowedArtist(user_id=user.id, artist_id=artist.id))
        for album in rng.sample(list(db.scalars(select(Album))), 3):
            db.add(SavedAlbum(user_id=listener.id, album_id=album.id))

        plays: dict[uuid.UUID, int] = {}
        listeners = [listener, premium_user, *extras]
        for day in range(30):
            for user in rng.sample(listeners, rng.randint(3, len(listeners))):
                taste = rng.choice(list(by_style.values()))
                for _ in range(rng.randint(1, 6)):
                    song = rng.choice(taste if rng.random() < 0.7 else songs)
                    completed = rng.random() < 0.75
                    ms = song.duration_ms if completed else rng.randint(5_000, song.duration_ms)
                    played_at = now - timedelta(days=day, minutes=rng.randint(0, 1400))
                    db.add(ListeningHistory(user_id=user.id, song_id=song.id, played_at=played_at, ms_played=ms,
                                            completed=completed, context_type="album", context_id=song.album_id))
                    if ms >= min(30_000, song.duration_ms):
                        plays[song.id] = plays.get(song.id, 0) + 1
        for song_id, count in plays.items():
            db.execute(update(Song).where(Song.id == song_id).values(play_count=count * 37))  # scaled for display
        db.commit()

    print(f"\nSeeded {len(songs)} tracks by {len(CATALOG)} artists, {len(DEMO_USERS) + len(EXTRA_LISTENERS)} users.")
    print("Demo accounts (password = SEED_DEMO_PASSWORD):")
    for email, _, role, premium in DEMO_USERS:
        print(f"  {email:<22} {role.value}{' + premium' if premium else ''}")


def _dotenv(key: str) -> str | None:
    from app.core.config import BACKEND_DIR

    env = BACKEND_DIR / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip() or None
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete all existing data first (development only)")
    args = parser.parse_args()
    if args.reset:
        reset()
    seed()

"""Re-apply rights rules and screening to every stored provider track.

    uv run python -m scripts.recheck_rights

Run after changing COMMERCIAL_DEPLOYMENT, MUSIC_DOWNLOADS_ENABLED or the screening rules. It never
contacts providers, and never re-enables a track a provider restricted; playback re-verifies those.
"""

from app.db.session import SessionLocal
from app.music.ingest import recheck_rights


def main() -> None:
    with SessionLocal() as db:
        checked, lost = recheck_rights(db)
    print(f"Checked {checked} provider tracks; {lost} are no longer playable.")


if __name__ == "__main__":
    main()

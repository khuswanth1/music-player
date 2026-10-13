import uuid

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.errors import Forbidden, NotFound
from app.core.security import create_stream_token, decode_token
from app.models import Song
from app.music import federation
from app.schemas.catalog import StreamUrl
from app.services import catalog as catalog_svc
from app.services.entitlements import require_premium
from app.storage.backends import LocalStorage, get_storage
from app.storage.ranges import parse_range

router = APIRouter(tags=["streaming"])


# Provider URLs don't carry our tokens; the player re-requests one after this long anyway.
_EXTERNAL_URL_TTL = 6 * 3600


@router.get("/songs/{song_id}/stream-url", response_model=StreamUrl,
            responses={451: {"description": "The track's license or provider terms don't permit playback here"}})
def stream_url(song_id: uuid.UUID, user: CurrentUser, db: DB):
    """Entitlement check happens here. Hosted songs get a URL with a token scoped to this one song;
    provider tracks get the provider's own authorized stream, after their rights are (re)verified."""
    song = catalog_svc.get_song(db, song_id, user)
    if not song.is_local:
        url = federation.playback_url(db, song)
        return StreamUrl(url=url, expires_in=_EXTERNAL_URL_TTL, mime_type=None, external=True,
                         attribution=song.attribution)
    if not song.audio_key:
        raise NotFound("This song has no audio yet", code="audio_missing")
    if song.is_premium:
        require_premium(db, user, "This release")
    ttl = get_settings().stream_token_ttl_minutes * 60
    token = create_stream_token(user.id, song.id)
    return StreamUrl(url=f"/api/v1/stream/{song.id}?token={token}", expires_in=ttl, mime_type=song.audio_mime)


@router.head("/stream/{song_id}", response_class=Response, include_in_schema=False)
@router.get("/stream/{song_id}", response_class=Response,
            summary="Stream audio with HTTP Range support (token from /songs/{id}/stream-url)")
def stream(song_id: uuid.UUID, request: Request, db: DB, token: str = Query(...)):
    claims = decode_token(token, "stream")
    if claims.get("song") != str(song_id):
        raise Forbidden("Token is not valid for this song")
    song = db.get(Song, song_id)
    if song is None or not song.audio_key or not song.is_local:
        raise NotFound("Audio not found")

    storage = get_storage()
    direct = storage.presigned_url(song.audio_key, 3600)
    if direct:
        return RedirectResponse(direct, status_code=302)

    size = storage.size(song.audio_key)
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600",
               "Content-Type": song.audio_mime or "application/octet-stream"}
    byte_range = parse_range(request.headers.get("range"), size)
    if byte_range is None:
        start, end, status = 0, size - 1, 200
    else:
        (start, end), status = byte_range, 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    if request.method == "HEAD":
        return Response(status_code=status, headers=headers)
    return StreamingResponse(storage.iter_range(song.audio_key, start, end), status_code=status,
                             headers=headers, media_type=headers["Content-Type"])


@router.get("/media/{key:path}", response_class=Response, summary="Public images (covers, avatars)")
def media(key: str):
    if not key.startswith("images/"):
        raise NotFound("Not found")  # audio is only reachable through the stream endpoint
    storage = get_storage()
    try:
        if not storage.exists(key):
            raise NotFound("Not found")
    except ValueError as exc:
        raise NotFound("Not found") from exc
    if isinstance(storage, LocalStorage):
        # Keys are content-unique UUIDs, so responses can be cached forever.
        return FileResponse(storage.path(key), headers={"Cache-Control": "public, max-age=31536000, immutable"})
    return RedirectResponse(storage.presigned_url(key, 3600), status_code=302)

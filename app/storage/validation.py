"""Upload validation: size limits enforced while reading, and content checked by its bytes, not its name."""

import tempfile
import uuid
from dataclasses import dataclass
from typing import BinaryIO

import mutagen
from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import AppError


class InvalidUpload(AppError):
    status_code = 422
    code = "invalid_upload"


class UploadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


@dataclass
class ValidatedFile:
    fileobj: BinaryIO
    size: int
    content_type: str
    extension: str
    duration_ms: int | None = None

    def key(self, prefix: str) -> str:
        return f"{prefix}/{uuid.uuid4().hex}.{self.extension}"


def _spool(upload: UploadFile, max_bytes: int) -> tuple[BinaryIO, int]:
    tmp = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # noqa: SIM115 (returned to caller, who closes it)
    size = 0
    while chunk := upload.file.read(64 * 1024):
        size += len(chunk)
        if size > max_bytes:
            tmp.close()
            raise UploadTooLarge(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
        tmp.write(chunk)
    if size == 0:
        tmp.close()
        raise InvalidUpload("File is empty")
    tmp.seek(0)
    return tmp, size


_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)


def validate_image(upload: UploadFile) -> ValidatedFile:
    fileobj, size = _spool(upload, get_settings().max_image_upload_mb * 1024 * 1024)
    head = fileobj.read(16)
    fileobj.seek(0)
    for signature, mime, ext in _IMAGE_SIGNATURES:
        if head.startswith(signature):
            return ValidatedFile(fileobj, size, mime, ext)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ValidatedFile(fileobj, size, "image/webp", "webp")
    fileobj.close()
    raise InvalidUpload("Image must be a JPEG, PNG or WebP file")


# mutagen class name → (mime type, extension)
_AUDIO_TYPES = {
    "MP3": ("audio/mpeg", "mp3"),
    "OggVorbis": ("audio/ogg", "ogg"),
    "OggOpus": ("audio/ogg", "opus"),
    "FLAC": ("audio/flac", "flac"),
    "WAVE": ("audio/wav", "wav"),
    "MP4": ("audio/mp4", "m4a"),
}


def validate_audio(upload: UploadFile) -> ValidatedFile:
    fileobj, size = _spool(upload, get_settings().max_audio_upload_mb * 1024 * 1024)
    try:
        audio = mutagen.File(fileobj)
    except Exception:  # mutagen raises many format-specific errors on corrupt input
        audio = None
    fileobj.seek(0)
    if audio is None or type(audio).__name__ not in _AUDIO_TYPES:
        fileobj.close()
        raise InvalidUpload("Audio must be MP3, OGG (Vorbis/Opus), FLAC, WAV or M4A")
    length = getattr(audio.info, "length", 0) or 0
    if length <= 0 or length > 60 * 60:
        fileobj.close()
        raise InvalidUpload("Audio duration must be between 0 and 60 minutes")
    mime, ext = _AUDIO_TYPES[type(audio).__name__]
    return ValidatedFile(fileobj, size, mime, ext, duration_ms=round(length * 1000))

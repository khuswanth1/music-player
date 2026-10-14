"""Provider registry. To add a source: implement `MusicProvider`, register it here (or call
`register_provider` from a plugin module), and list its key in MUSIC_PROVIDERS. Nothing else changes."""

import threading

from app.core.config import get_settings
from app.music.providers.audius import AudiusProvider
from app.music.providers.base import Capability, MetadataRecording, MusicProvider, ProviderTrack
from app.music.providers.ccmixter import CcMixterProvider
from app.music.providers.internet_archive import InternetArchiveProvider
from app.music.providers.itunes import ITunesProvider
from app.music.providers.jamendo import JamendoProvider
from app.music.providers.musicbrainz import MusicBrainzProvider
from app.music.providers.openverse import OpenverseProvider
from app.music.providers.wikimedia import WikimediaCommonsProvider

_FACTORIES: dict[str, type[MusicProvider]] = {
    cls.key: cls for cls in (JamendoProvider, InternetArchiveProvider, AudiusProvider, OpenverseProvider,
                             CcMixterProvider, MusicBrainzProvider, ITunesProvider, WikimediaCommonsProvider)
}
_instances: dict[str, MusicProvider] = {}
_lock = threading.Lock()


def register_provider(cls: type[MusicProvider]) -> None:
    _FACTORIES[cls.key] = cls
    _instances.pop(cls.key, None)


def unregister_provider(key: str) -> None:
    _FACTORIES.pop(key, None)
    _instances.pop(key, None)


def reset_providers() -> None:
    """Drop cached instances so they're rebuilt from current settings (tests, config reloads)."""
    with _lock:
        _instances.clear()


def known_providers() -> list[MusicProvider]:
    """Every registered provider, enabled or not (for the Sources page)."""
    with _lock:
        for key, cls in _FACTORIES.items():
            if key not in _instances:
                _instances[key] = cls()
        return [_instances[k] for k in _FACTORIES]


def is_enabled(provider: MusicProvider) -> bool:
    return provider.key in get_settings().music_providers and provider.is_configured()


def enabled_providers(capability: Capability | None = None) -> list[MusicProvider]:
    order = get_settings().music_providers
    providers = [p for p in known_providers() if is_enabled(p) and (capability is None or capability in p.capabilities)]
    return sorted(providers, key=lambda p: order.index(p.key))


def get_provider(key: str) -> MusicProvider | None:
    return next((p for p in known_providers() if p.key == key), None)


__all__ = ["Capability", "MetadataRecording", "MusicProvider", "ProviderTrack", "enabled_providers", "get_provider",
           "is_enabled", "known_providers", "register_provider", "reset_providers"]

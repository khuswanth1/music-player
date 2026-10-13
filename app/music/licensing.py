"""Track-level license classification and playback/download rights.

Two separate questions decide what we may do with a provider track:

1. **The license** — what the rights holder permits (parsed from a Creative Commons URL or name).
2. **The provider's terms** — whether the provider lets third-party apps stream (and link downloads of)
   its catalog through its API.

A track is playable only if both allow it. Downloads additionally need the license to permit
redistribution, the provider to permit download links, and the provider to say the specific track is
downloadable. We never copy provider audio to our own storage; playback and downloads go to the
provider's own authorized URLs.
"""

import re
from dataclasses import dataclass

from app.models.catalog import Availability


@dataclass(frozen=True)
class License:
    code: str  # cc0 | pdm | cc-by | cc-by-sa | cc-by-nd | cc-by-nc | cc-by-nc-sa | cc-by-nc-nd | platform | unknown
    name: str  # human label, e.g. "CC BY-SA 4.0"
    url: str | None = None
    version: str | None = None

    @property
    def is_open(self) -> bool:
        """A recognized public license (Creative Commons or a public-domain dedication)."""
        return self.code.startswith("cc") or self.code == "pdm"

    @property
    def commercial_use(self) -> bool:
        return self.is_open and "-nc" not in self.code

    @property
    def derivatives(self) -> bool:
        return self.is_open and "-nd" not in self.code

    @property
    def attribution_required(self) -> bool:
        return self.code.startswith("cc-by") or self.code == "platform"

    @property
    def redistribution(self) -> bool:
        """Every CC license and public-domain mark permits verbatim (non-commercial at least) copies."""
        return self.is_open


UNKNOWN = License("unknown", "License not stated")
# "All rights reserved" with streaming granted through the provider's platform/API terms (e.g. Audius).
PLATFORM_STREAM_ONLY = License("platform", "All rights reserved — streaming licensed via provider")

_CC_URL = re.compile(r"creativecommons\.org/(licenses|publicdomain)/([a-z-]+)(?:/(\d+(?:\.\d+)?))?", re.I)
# The six current CC licenses (and legacy element orders). Retired ones such as Sampling+ or the
# pre-2.0 licenses without BY only allowed limited reuse, so they deliberately stay UNKNOWN.
_CANONICAL = {"by": "by", "by-sa": "by-sa", "by-nd": "by-nd", "by-nc": "by-nc", "by-nc-sa": "by-nc-sa",
              "by-nc-nd": "by-nc-nd", "by-nd-nc": "by-nc-nd", "by-sa-nc": "by-nc-sa"}


def _cc(kind: str, version: str | None, url: str | None) -> License:
    slug = _CANONICAL.get(kind.lower())
    if slug is None:
        return UNKNOWN
    return License(f"cc-{slug}", f"CC {slug.upper()}{' ' + version if version else ''}", url, version)


def parse_license(value: str | None) -> License:
    """Classify a license URL (preferred) or name. Unrecognized input is UNKNOWN, never assumed open."""
    if not value:
        return UNKNOWN
    text = value.strip()
    url = text if text.lower().startswith(("http://", "https://", "//")) else None
    if url:
        url = "https:" + url if url.startswith("//") else url
        url = re.sub(r"^http://", "https://", url, flags=re.I)
    m = _CC_URL.search(text)
    if m:
        family, kind, version = m.group(1).lower(), m.group(2).lower(), m.group(3)
        if family == "publicdomain":
            if kind == "zero":
                return License("cc0", f"CC0 {version or '1.0'}", url, version or "1.0")
            if kind == "mark":
                return License("pdm", "Public Domain Mark", url, version)
            return UNKNOWN
        return _cc(kind, version, url)

    # Names, e.g. Openverse ("by-sa" + version) or ccMixter ("Attribution Noncommercial").
    low = re.sub(r"[\s_]+", " ", text.lower()).strip()
    if low in ("cc0", "cc-0", "cc zero", "creative commons zero", "public domain dedication"):
        return License("cc0", "CC0 1.0", None, "1.0")
    if low in ("pdm", "public domain", "public domain mark"):
        return License("pdm", "Public Domain Mark")
    short = low.removeprefix("cc ").removeprefix("cc-").replace(" ", "-")
    if short in _CANONICAL:
        return _cc(short, None, None)
    words = set(re.findall(r"[a-z]+", low))
    if "attribution" in words or low.startswith("creative commons"):
        if "sampling" in words:
            return UNKNOWN
        parts = ["by"]
        if words & {"noncommercial", "non", "nc"}:
            parts.append("nc")
        if words & {"sharealike", "share"}:
            parts.append("sa")
        if words & {"noderivs", "noderivatives", "derivatives", "derivs"} and "sa" not in parts:
            parts.append("nd")
        return _cc("-".join(parts), None, None)
    return UNKNOWN


def with_version(lic: License, version: str | None) -> License:
    if not version or lic.version or not lic.code.startswith("cc-"):
        return lic
    slug = lic.code.removeprefix("cc-")
    return License(lic.code, f"{lic.name} {version}",
                   lic.url or f"https://creativecommons.org/licenses/{slug}/{version}/", version)


def attribution_line(title: str, artist: str, lic: License, provider_name: str) -> str:
    """TASL-style attribution: Title, Author, Source, License."""
    if lic.code == "platform":
        return f'"{title}" by {artist}. All rights reserved; streamed via {provider_name}.'
    if lic.code in ("cc0", "pdm"):
        return f'"{title}" by {artist} ({lic.name}), via {provider_name}.'
    return f'"{title}" by {artist}, licensed under {lic.name}, via {provider_name}.'


@dataclass(frozen=True)
class ProviderPolicy:
    """What a provider's terms allow third-party apps to do with its catalog."""
    stream: bool = True               # its API terms permit streaming its audio URLs in other apps
    requires_open_license: bool = True  # only stream tracks with a recognized open license
    download_links: bool = False      # its terms permit linking to its download URLs
    notes: str = ""


@dataclass(frozen=True)
class Rights:
    availability: Availability
    stream_allowed: bool
    download_allowed: bool
    reason: str | None = None


def evaluate(*, lic: License, policy: ProviderPolicy, has_stream: bool, has_download: bool,
             provider_download_allowed: bool, restrictions: list[str], commercial_deployment: bool,
             downloads_enabled: bool) -> Rights:
    """Decide playback and download rights for one track. Every 'no' carries a user-facing reason."""
    if restrictions:
        return Rights(Availability.restricted, False, False, restrictions[0])
    if not has_stream:
        return Rights(Availability.unavailable, False, False, "No authorized audio stream from the provider")
    if not policy.stream:
        return Rights(Availability.restricted, False, False, "Provider terms don't permit streaming in other apps")
    if policy.requires_open_license and not lic.is_open:
        return Rights(Availability.restricted, False, False,
                      "License could not be verified" if lic.code == "unknown" else f"{lic.name} doesn't permit streaming")
    if commercial_deployment and lic.is_open and not lic.commercial_use:
        return Rights(Availability.restricted, False, False,
                      f"{lic.name} is non-commercial and this service is configured as commercial")
    download = (downloads_enabled and has_download and lic.redistribution and policy.download_links
                and provider_download_allowed)
    return Rights(Availability.playable, True, download, None)

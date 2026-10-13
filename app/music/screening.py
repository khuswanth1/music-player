"""Second-opinion checks on a provider's license claim.

Open catalogs are mostly honest, but anyone can upload to some of them and pick a license. A license
field alone is not proof, so before a track can be played we also reject claims that can't be true:

* **Public Domain Mark on a recent recording.** In the US, sound recordings published before 1923
  entered the public domain in 2022, and those from 1923–1946 enter it 100 years after publication.
  A PDM is therefore only credible for recordings published at least 100 years ago (and a known date).
* **Commercial releases re-uploaded from piracy sites**, recognisable by download-site watermarks
  ("Mp3Mad.Com", "PagalWorld") or major-label names in the title, artist or album.
* **Public-domain / CC0 claims on film-song compilations** ("Bollywood hits", "1000 songs" packs, jukeboxes).
* **Film or commercial songs on open-upload platforms** (Internet Archive, Audius), whatever license the
  uploader picked: titles like "Naatu Naatu Song from (RRR) Telugu Version" or "RRR Songs | Lyrical Video"
  are almost never uploaded by the rights holder.

These are heuristics: they block the obvious cases and err on the side of not playing. Anything that slips
through can be taken down by an editor or by a signed rights notice (see app/music/rights.py).
"""

import re
from datetime import date

from app.music.providers.base import ProviderTrack

# Watermarks of download/piracy sites commonly left in file names and tags.
_PIRACY_SITES = (
    r"mp3mad", r"djjohal", r"royaljatt", r"pagalworld", r"pagal\s*world", r"mr-?jatt", r"djpunjab", r"songs\.pk",
    r"songspk", r"downloadming", r"djmaza", r"wapking", r"webmusic\.in", r"mp3skull", r"starmusiq", r"masstamilan",
    r"isaimini", r"naasongs", r"teluguwap", r"atozmp3", r"sensongs", r"freshmaza", r"kuttyweb", r"tamilwire",
    r"mp3juices", r"songslover", r"bestwap", r"jattjugadi", r"mymp3song", r"hindimp3", r"raagtune", r"compgeek",
    r"mp3tau", r"bestmp3", r"jiosaavn", r"gaana\.com", r"yt1s", r"y2mate", r"ytmp3",
)
# Labels whose catalogs are not openly licensed. Matched as whole words in title/artist/album only.
_MAJOR_LABELS = (
    r"t-series", r"tseries", r"zee music", r"sony music", r"saregama", r"tips (music|industries)", r"aditya music",
    r"lahari music", r"venus (records|music)", r"yrf music", r"yash raj", r"eros (now|music)", r"speed records",
    r"universal music", r"warner music", r"emi music", r"think music", r"junglee music", r"shemaroo", r"hybe",
    r"sm entertainment", r"jyp entertainment",
    r"yg entertainment", r"avex", r"rotana", r"mazzika",
)
_COMMERCIAL = re.compile("|".join(f"(?:{p})" for p in _PIRACY_SITES + _MAJOR_LABELS), re.IGNORECASE)
_COMPILATION = re.compile(
    r"\b(bollywood|tollywood|kollywood|mollywood|sandalwood|film\s*songs?|movie\s*songs?|cinema\s*songs?|"
    r"from\s+the\s+(motion\s+picture|film|movie)|original\s+(motion\s+picture\s+)?soundtrack|\bost\b|jukebox|"
    r"hit\s*songs|super\s*hits|top\s*\d+|collections?\s+of\s+\d+|\d{3,}\s+songs|video\s+song|full\s+album|"
    r"remix(es)?\s+collection)\b", re.IGNORECASE)

# Film-soundtrack and re-upload naming. Applied to open-upload platforms only, where uploaders rarely own it.
_FILM_SONG = re.compile(
    r"\(\s*from\b|\bfrom\s*\(|\bsongs?\s+from\b|\b(movie|film|cinema)\s+(songs?|version|soundtrack|ost)\b|"
    r"(?-i:\b[A-Z0-9]{2,5}\s+[Ss]ongs\b)|"  # "RRR Songs": a film's acronym, case-sensitive on purpose
    r"\b(lyrical|lyrics?\s+video|video\s+song|audio\s+song|full\s+song|title\s+song|item\s+song|"
    r"official\s+(video|audio|music\s+video)|(telugu|tamil|hindi|kannada|malayalam|bengali|punjabi|marathi|bhojpuri)\s+version|"
    r"dj\s+songs?|whatsapp\s+status|ringtone)\b", re.IGNORECASE)

PUBLIC_DOMAIN_AGE_YEARS = 100


def screen(t: ProviderTrack, *, open_uploads: bool = False, today: date | None = None) -> str | None:
    """A user-facing reason to refuse playback despite the stated license, or None."""
    text = " | ".join(filter(None, [t.title, t.artist_name, t.album_title, t.source_url, t.stream_url]))
    if _COMMERCIAL.search(text):
        return "Looks like a commercial release re-uploaded without authorization"
    if t.license.code in ("pdm", "cc0") and _COMPILATION.search(" | ".join([text, *t.tags])):
        return "A public-domain claim isn't credible for a commercial film or hits compilation"
    if open_uploads:
        naming = " | ".join(filter(None, [t.title, t.album_title]))
        if _FILM_SONG.search(naming) or _COMPILATION.search(naming):
            return "Looks like a film or commercial song uploaded by someone other than its rights holder"
    if t.license.code == "pdm":
        year = (today or date.today()).year
        if t.release_date is None or t.release_date.year > year - PUBLIC_DOMAIN_AGE_YEARS:
            return "Public-domain claim can't be verified for a recording this recent"
    return None

"""Understand search phrases such as "telugu old songs 1990" or "korean movie soundtracks".

Only picks out hints that are unambiguous (a language name, a country name, a year or decade, "latest"/"old",
"movie"); everything else stays in `rest` and is sent to the providers as plain text.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.music import languages as langs
from app.music.countries import find_country

_LANGUAGE_NAMES: dict[str, str] = {}
for _lang in langs.LANGUAGES:
    for _name in (_lang.name, _lang.native_name):
        _LANGUAGE_NAMES.setdefault(unicodedata.normalize("NFKC", _name).casefold(), _lang.code)
_LANGUAGE_NAMES.update({"bollywood": "hi", "chinese": "zh", "mandarin": "zh", "farsi": "fa", "tollywood": "te"})

_FILLER = {"songs", "song", "music", "tracks", "track", "hits", "singers", "singer", "artists", "artist", "albums", "album"}
_NEW = {"latest", "new", "newest", "recent", "fresh"}
_OLD = {"old", "oldies", "classic", "classics", "vintage", "retro", "golden"}
_MOVIE = {"movie", "movies", "film", "films", "soundtrack", "soundtracks", "ost", "cinema"}
_PODCAST = {"podcast", "podcasts", "episode", "episodes"}


@dataclass
class Hints:
    language: str | None = None
    country: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    era: str | None = None  # "latest" | "old"
    movie: bool = False
    podcast: bool = False
    rest: str = ""  # what remains after hints and filler words are removed


def parse(text: str) -> Hints:
    h = Hints()
    country, remaining = find_country(text)
    h.country = country
    tokens = re.findall(r"[^\s,]+", remaining)
    kept = []
    for tok in tokens:
        low = unicodedata.normalize("NFKC", tok).casefold()
        if low in _NEW:
            h.era = h.era or "latest"
        elif low in _OLD:
            h.era = "old"
        elif low in _MOVIE:
            h.movie = True
        elif low in _PODCAST:
            h.podcast = True
        elif (m := re.fullmatch(r"((?:19|20)\d)0s", low)) or (m := re.fullmatch(r"(\d)0s", low)):
            digits = m.group(1)
            decade = int(digits) * 10 if len(digits) == 3 else (1900 + int(digits) * 10 if int(digits) >= 3 else 2000 + int(digits) * 10)
            h.year_from, h.year_to = decade, decade + 9
        elif re.fullmatch(r"(?:19|20)\d\d", low):
            h.year_from = h.year_to = int(low)
        elif low in _LANGUAGE_NAMES and h.language is None and len(low) > 2:
            h.language = _LANGUAGE_NAMES[low]
        elif low in _FILLER:
            continue
        else:
            kept.append(tok)
    h.rest = " ".join(kept)
    if not h.rest and not (h.language or h.country or h.year_from or h.era or h.movie or h.podcast):
        h.rest = text.strip()  # only filler words ("songs"): search for them literally rather than for everything
    if h.era == "old" and h.year_to is None:
        h.year_to = 2005  # "old"/"classic" = released by 2005, unless a year/decade was named
    return h

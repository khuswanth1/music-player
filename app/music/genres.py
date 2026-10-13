"""Canonical world-genre list and provider-tag normalization.

Providers tag music freely ("hiphop", "Hip-Hop/Rap", "desi hip hop"). We map tags to a fixed set of
genres so browsing is consistent across sources; tags we don't recognize are ignored, not invented.
Genre rows are created on first use, so admins can still rename or recolor them.
"""

import re
import unicodedata

# name -> (color, aliases). Order matters only for readability.
CANONICAL: dict[str, tuple[str, tuple[str, ...]]] = {
    "Pop": ("#f472b6", ("pop", "pop music", "europop", "synthpop", "dance pop", "indie pop", "electropop")),
    "Rock": ("#ef4444", ("rock", "alternative rock", "alt rock", "hard rock", "classic rock", "indie rock",
                         "progressive rock", "psychedelic rock", "post rock", "soft rock", "pop rock", "garage rock")),
    "Metal": ("#71717a", ("metal", "heavy metal", "death metal", "black metal", "thrash metal", "doom metal")),
    "Punk": ("#f97316", ("punk", "punk rock", "hardcore punk", "pop punk", "post punk")),
    "Indie": ("#a3e635", ("indie", "independent", "indie folk", "lo fi indie")),
    "Alternative": ("#84cc16", ("alternative", "alt", "grunge", "shoegaze", "emo")),
    "Hip-Hop": ("#eab308", ("hip hop", "hiphop", "hip-hop", "rap", "hip hop rap", "trap", "boom bap", "desi hip hop", "grime",
                            "drill")),
    "R&B & Soul": ("#c084fc", ("r&b", "rnb", "r and b", "rhythm and blues", "soul", "neo soul", "motown")),
    "Funk": ("#fb923c", ("funk", "disco", "boogie")),
    "Jazz": ("#60a5fa", ("jazz", "smooth jazz", "acid jazz", "bebop", "swing", "jazz fusion", "big band", "nu jazz")),
    "Blues": ("#3b82f6", ("blues", "delta blues", "rhythm blues")),
    "Country": ("#d97706", ("country", "americana", "bluegrass", "country music")),
    "Folk": ("#65a30d", ("folk", "folk music", "traditional", "acoustic folk", "singer songwriter", "singer-songwriter",
                         "world folk", "folklore")),
    "Classical": ("#e5e7eb", ("classical", "classical music", "orchestral", "baroque", "romantic", "chamber music",
                              "symphony", "piano classical", "contemporary classical", "modern classical")),
    "Opera": ("#f5d0fe", ("opera", "operetta", "aria")),
    "Electronic": ("#22d3ee", ("electronic", "electronica", "electro", "edm", "idm", "electronic music", "synth",
                               "glitch", "breakbeat")),
    "Dance": ("#2dd4bf", ("dance", "club", "eurodance", "electro house")),
    "House": ("#34d399", ("house", "deep house", "tech house", "progressive house", "future house")),
    "Techno": ("#14b8a6", ("techno", "minimal techno", "detroit techno", "minimal")),
    "Trance": ("#06b6d4", ("trance", "psytrance", "goa trance", "progressive trance")),
    "Drum & Bass": ("#0ea5e9", ("drum and bass", "drum & bass", "drum n bass", "dnb", "jungle", "liquid funk")),
    "Dubstep": ("#6366f1", ("dubstep", "brostep", "riddim", "future bass")),
    "Ambient": ("#38bdf8", ("ambient", "dark ambient", "drone", "space music", "new age", "meditation", "relaxation",
                            "healing")),
    "Chillout": ("#7dd3fc", ("chillout", "chill out", "chill", "lounge", "downtempo", "trip hop", "trip-hop", "chillhop")),
    "Lo-Fi": ("#a78bfa", ("lo fi", "lofi", "lo-fi", "lofi hip hop", "lo-fi hip hop")),
    "Experimental": ("#a1a1aa", ("experimental", "avant garde", "avant-garde", "noise", "musique concrete",
                                 "sound art", "field recording", "field recordings")),
    "Soundtrack": ("#facc15", ("soundtrack", "film score", "score", "cinematic", "film music", "game music",
                               "video game", "trailer", "epic", "orchestral soundtrack")),
    "Reggae": ("#22c55e", ("reggae", "dub", "dancehall", "ska", "roots reggae", "rocksteady")),
    "Latin": ("#f43f5e", ("latin", "latin pop", "latin music", "musica latina", "tropical")),
    "Reggaeton": ("#e11d48", ("reggaeton", "reggaetón", "dembow", "urbano latino", "latin urban")),
    "Salsa": ("#fb7185", ("salsa", "merengue", "timba", "son cubano", "cuban")),
    "Bachata": ("#fda4af", ("bachata",)),
    "Cumbia": ("#fdba74", ("cumbia", "vallenato", "champeta")),
    "Tango": ("#be123c", ("tango", "milonga")),
    "Bossa Nova & MPB": ("#4ade80", ("bossa nova", "bossa", "mpb", "samba", "musica popular brasileira", "forro",
                                     "sertanejo", "brazilian")),
    "Flamenco": ("#dc2626", ("flamenco", "rumba flamenca", "sevillanas")),
    "Fado": ("#7c3aed", ("fado",)),
    "Chanson": ("#93c5fd", ("chanson", "french pop", "variete francaise", "variété française")),
    "Celtic": ("#16a34a", ("celtic", "irish folk", "scottish folk", "irish traditional")),
    "Afrobeats": ("#f59e0b", ("afrobeats", "afrobeat", "afropop", "afro pop", "afro", "amapiano", "afro house",
                              "naija")),
    "African": ("#ca8a04", ("highlife", "soukous", "mbalax", "kwaito", "gqom", "bongo flava", "benga", "juju",
                            "makossa", "rumba congolaise", "african", "mbaqanga")),
    "Arabic": ("#b45309", ("arabic", "arabic pop", "arab", "khaleeji", "rai", "raï", "dabke", "mahraganat",
                           "maqam", "tarab", "chaabi")),
    "Turkish & Persian": ("#92400e", ("turkish", "arabesk", "turkish pop", "persian", "persian pop", "iranian",
                                      "anatolian rock")),
    "K-Pop": ("#ec4899", ("k-pop", "kpop", "k pop", "korean pop", "k-indie", "k-r&b", "trot")),
    "J-Pop": ("#f9a8d4", ("j-pop", "jpop", "j pop", "japanese pop", "city pop", "j-rock", "jrock", "anime", "anison",
                          "vocaloid", "enka", "japanese")),
    "C-Pop": ("#fca5a5", ("c-pop", "cpop", "mandopop", "cantopop", "chinese pop", "guofeng")),
    "Filmi": ("#fbbf24", ("filmi", "bollywood", "tollywood", "kollywood", "sandalwood", "mollywood", "film songs",
                          "film song", "indian film", "movie songs", "cinema songs")),
    "Indian Classical": ("#fde68a", ("indian classical", "carnatic", "hindustani", "hindustani classical",
                                     "carnatic music", "raga", "raag", "dhrupad", "khayal", "thumri", "kriti")),
    "Devotional": ("#fef08a", ("devotional", "bhajan", "bhajans", "kirtan", "keertan", "bhakti", "aarti", "mantra",
                               "chant", "chanting", "gospel", "worship", "christian", "spiritual", "religious",
                               "hymn", "hymns", "nasheed", "shabad", "gurbani", "stotram", "slokas", "sloka")),
    "Sufi & Qawwali": ("#d9f99d", ("sufi", "qawwali", "ghazal", "ghazals", "sufi music")),
    "Bhangra & Punjabi": ("#facc15", ("bhangra", "punjabi pop", "giddha")),
    "Indian Folk": ("#bef264", ("indian folk", "lavani", "baul", "bihu", "janapada", "oggu katha", "garba", "dandiya",
                                "kolattam", "folk songs india", "rajasthani folk", "telugu folk", "tamil folk",
                                "gaana", "dappankuthu", "kuthu")),
    "Indian Pop": ("#fcd34d", ("indipop", "indi pop", "indian pop", "desi pop", "hindi pop", "indie india",
                               "independent indian")),
    "Southeast Asian": ("#86efac", ("dangdut", "gamelan", "luk thung", "mor lam", "v-pop", "opm", "pinoy",
                                    "keroncong", "t-pop", "thai pop")),
    "Children's": ("#fda4af", ("children", "children's", "kids", "lullaby", "lullabies", "nursery rhymes")),
    "Spoken Word": ("#d4d4d8", ("spoken word", "poetry", "spoken", "audiobook", "storytelling", "comedy")),
    "World": ("#10b981", ("world", "world music", "world fusion", "ethnic", "global", "worldbeat", "fusion")),
    "Instrumental": ("#94a3b8", ("instrumental", "instrumentals", "solo piano", "background music")),
}

_TAG_TO_GENRE: dict[str, str] = {}
for _name, (_color, _aliases) in CANONICAL.items():
    _TAG_TO_GENRE[_name.lower()] = _name
    for _alias in _aliases:
        _TAG_TO_GENRE[_alias] = _name


def _clean(tag: str) -> str:
    tag = unicodedata.normalize("NFKC", tag).casefold().strip()
    tag = re.sub(r"[_/]+", " ", tag)
    return re.sub(r"\s+", " ", tag)


def canonical_genre(tags: list[str] | tuple[str, ...]) -> str | None:
    """First provider tag that maps to a canonical genre, trying the tag as-is then without hyphens."""
    for raw in tags:
        if not raw:
            continue
        tag = _clean(str(raw))
        for candidate in (tag, tag.replace("-", " "), tag.replace("-", ""), tag.replace(" ", "")):
            if candidate in _TAG_TO_GENRE:
                return _TAG_TO_GENRE[candidate]
    return None


def color_for(name: str) -> str:
    return CANONICAL.get(name, ("#1db954", ()))[0]

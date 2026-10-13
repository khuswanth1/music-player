"""Pure logic: licenses and rights, languages, genres, rate limiting."""

import time
from datetime import date

import pytest

from app.models import Availability
from app.music import languages as langs
from app.music.genres import canonical_genre
from app.music.http import TokenBucket
from app.music.licensing import (
    PLATFORM_STREAM_ONLY,
    UNKNOWN,
    ProviderPolicy,
    attribution_line,
    evaluate,
    parse_license,
    with_version,
)

OPEN = ProviderPolicy(stream=True, requires_open_license=True, download_links=True)


@pytest.mark.parametrize(("value", "code", "name"), [
    ("http://creativecommons.org/licenses/by-sa/4.0/", "cc-by-sa", "CC BY-SA 4.0"),
    ("https://creativecommons.org/licenses/by-nc-nd/3.0/", "cc-by-nc-nd", "CC BY-NC-ND 3.0"),
    ("http://creativecommons.org/licenses/by-nd-nc/1.0/", "cc-by-nc-nd", "CC BY-NC-ND 1.0"),
    ("//creativecommons.org/licenses/by/2.5/", "cc-by", "CC BY 2.5"),
    ("http://creativecommons.org/publicdomain/zero/1.0/", "cc0", "CC0 1.0"),
    ("https://creativecommons.org/publicdomain/mark/1.0/", "pdm", "Public Domain Mark"),
    ("Attribution Noncommercial", "cc-by-nc", "CC BY-NC"),
    ("Attribution Share-Alike", "cc-by-sa", "CC BY-SA"),
    ("Attribution-NonCommercial-NoDerivatives 4.0 International", "cc-by-nc-nd", "CC BY-NC-ND"),
    ("by-sa", "cc-by-sa", "CC BY-SA"),
    ("cc0", "cc0", "CC0 1.0"),
])
def test_parse_license_recognizes_open_licenses(value, code, name):
    lic = parse_license(value)
    assert (lic.code, lic.name) == (code, name)
    assert lic.is_open and lic.redistribution


@pytest.mark.parametrize("value", [
    None, "", "All rights reserved", "Creative Commons Sampling Plus 1.0",
    "http://creativecommons.org/licenses/sampling+/1.0/", "http://creativecommons.org/licenses/nc-sampling+/1.0/",
    "https://example.com/my-license", "Standard YouTube License",
])
def test_unrecognized_licenses_are_never_assumed_open(value):
    assert parse_license(value) is UNKNOWN or parse_license(value).code == "unknown"


def test_license_permissions():
    assert parse_license("https://creativecommons.org/licenses/by-nc/4.0/").commercial_use is False
    assert parse_license("https://creativecommons.org/licenses/by-nd/4.0/").derivatives is False
    assert parse_license("https://creativecommons.org/licenses/by/4.0/").attribution_required is True
    assert parse_license("https://creativecommons.org/publicdomain/zero/1.0/").attribution_required is False
    assert PLATFORM_STREAM_ONLY.is_open is False and PLATFORM_STREAM_ONLY.redistribution is False
    versioned = with_version(parse_license("by-sa"), "3.0")
    assert versioned.name == "CC BY-SA 3.0" and versioned.url == "https://creativecommons.org/licenses/by-sa/3.0/"


def _rights(**overrides):
    args = dict(lic=parse_license("https://creativecommons.org/licenses/by/4.0/"), policy=OPEN, has_stream=True,
                has_download=True, provider_download_allowed=True, restrictions=[], commercial_deployment=False,
                downloads_enabled=True)
    args.update(overrides)
    return evaluate(**args)


def test_rights_open_license_is_playable_and_downloadable():
    r = _rights()
    assert (r.availability, r.stream_allowed, r.download_allowed, r.reason) == (Availability.playable, True, True, None)


def test_rights_every_refusal_has_a_reason():
    cases = {
        "restricted": _rights(restrictions=["Gated by the artist"]),
        "no stream": _rights(has_stream=False),
        "unknown license": _rights(lic=UNKNOWN),
        "platform license where open is required": _rights(lic=PLATFORM_STREAM_ONLY),
        "provider forbids streaming": _rights(policy=ProviderPolicy(stream=False)),
        "NC on commercial deployment": _rights(lic=parse_license("https://creativecommons.org/licenses/by-nc/4.0/"),
                                               commercial_deployment=True),
    }
    for label, r in cases.items():
        assert not r.stream_allowed and not r.download_allowed, label
        assert r.reason, label
    assert cases["no stream"].availability == Availability.unavailable
    assert cases["unknown license"].availability == Availability.restricted


def test_rights_noncommercial_is_fine_on_a_free_service():
    r = _rights(lic=parse_license("https://creativecommons.org/licenses/by-nc-sa/4.0/"))
    assert r.stream_allowed and r.download_allowed


def test_rights_downloads_need_license_provider_and_track_permission():
    assert not _rights(provider_download_allowed=False).download_allowed
    assert not _rights(policy=ProviderPolicy(stream=True, download_links=False)).download_allowed
    assert not _rights(downloads_enabled=False).download_allowed
    assert not _rights(has_download=False).download_allowed
    stream_only = _rights(lic=PLATFORM_STREAM_ONLY, policy=ProviderPolicy(stream=True, requires_open_license=False))
    assert stream_only.stream_allowed and not stream_only.download_allowed


def test_attribution_line():
    lic = parse_license("https://creativecommons.org/licenses/by-sa/4.0/")
    assert attribution_line("Song", "Artist", lic, "Jamendo") == '"Song" by Artist, licensed under CC BY-SA 4.0, via Jamendo.'


@pytest.mark.parametrize(("value", "code"), [
    ("te", "te"), ("tel", "te"), ("Telugu", "te"), ("తెలుగు", "te"), ("te-IN", "te"), ("pt_BR", "pt"),
    ("zh-Hant", "zh"), ("chi", "zh"), ("Mandarin", "zh"), ("ger", "de"), ("Farsi", "fa"), ("Panjabi", "pa"),
    ("Greek (modern)", "el"), ("kok", "kok"), ("Konkani", "kok"), ("Bhojpuri", "bho"), ("yue", "yue"),
    ("tel; eng", "te"), ("Hindi language", "hi"), ("instrumental", "zxx"), ("Bangla", "bn"),
])
def test_normalize_language(value, code):
    assert langs.normalize(value) == code


@pytest.mark.parametrize("value", [None, "", "und", "mul", "Klingon", "xx", "unknown"])
def test_normalize_unknown_language_returns_none(value):
    assert langs.normalize(value) is None


def test_language_catalog_covers_iso_639_1_and_indian_scheduled_languages():
    two_letter = [c for c in langs.BY_CODE if len(c) == 2]
    assert len(two_letter) >= 180
    scheduled = {"as", "bn", "brx", "doi", "gu", "hi", "kn", "ks", "kok", "mai", "ml", "mni", "mr", "ne", "or", "pa",
                 "sa", "sat", "sd", "ta", "te", "ur"}
    assert scheduled <= set(langs.BY_CODE)
    assert all(lang.region in langs.REGIONS for lang in langs.LANGUAGES)
    assert set(langs.FEATURED) <= set(langs.BY_CODE)


@pytest.mark.parametrize(("texts", "code"), [
    (("నాటు నాటు",), "te"), (("ಕನ್ನಡ ಹಾಡು",), "kn"), (("தமிழ் பாடல்",), "ta"), (("മലയാളം",), "ml"),
    (("ਪੰਜਾਬੀ",), "pa"), (("사랑해요",), "ko"), (("夜に駆ける", "YOASOBI"), "ja"), (("Telugu Tech",), None),
    (("हिन्दी गीत",), None),  # Devanagari is shared by several languages: no guess
    (("月亮代表我的心",), None),  # Han alone could be Chinese or Japanese
    (("ñ",), None),
])
def test_script_detection_only_for_unambiguous_scripts(texts, code):
    assert langs.detect_from_script(*texts) == code


@pytest.mark.parametrize(("tags", "genre"), [
    (["Hip-Hop/Rap"], "Hip-Hop"), (["kpop"], "K-Pop"), (["carnatic"], "Indian Classical"), (["bhajan"], "Devotional"),
    (["unknowntag", "Bollywood"], "Filmi"), (["drum_and_bass"], "Drum & Bass"), (["lo-fi"], "Lo-Fi"),
    (["qawwali"], "Sufi & Qawwali"), (["telugu"], None), ([], None),
])
def test_canonical_genre(tags, genre):
    assert canonical_genre(tags) == genre


def _pt(title="Song", *, license_url="https://creativecommons.org/licenses/by/4.0/", album=None, released=None,
        artist="Artist", tags=None):
    from app.music.providers.base import ProviderTrack

    return ProviderTrack(provider="x", provider_track_id="1", title=title, artist_name=artist, album_title=album,
                         release_date=released, license=parse_license(license_url), tags=tags or [],
                         stream_url="https://cdn.test/a.mp3")


PDM = "https://creativecommons.org/publicdomain/mark/1.0/"


@pytest.mark.parametrize(("track_args", "blocked"), [
    # Real-world pattern: commercial Bollywood songs re-uploaded with a Public Domain Mark.
    (dict(title="Bheegi Bheegi Raaton Mein (Mp3Mad.Com)", license_url=PDM,
          album="90s Romantic Hit Songs hindi- Collections of 1000 songs"), True),
    (dict(title="Aaj Phir", artist="T-Series"), True),
    (dict(title="Tum Hi Ho", album="Aashiqui 2 [PagalWorld]"), True),
    (dict(title="Classic Hits", license_url="https://creativecommons.org/publicdomain/zero/1.0/", tags=["bollywood"]), True),
    (dict(title="Recent Song", license_url=PDM, released=date(1995, 1, 1)), True),
    (dict(title="Undated Song", license_url=PDM), True),
    (dict(title="Wax Cylinder Aria", license_url=PDM, released=date(1910, 5, 1)), False),
    (dict(title="Monsoon Raga"), False),
    (dict(title="Hits Different", license_url="https://creativecommons.org/licenses/by-sa/4.0/", tags=["pop"]), False),
])
def test_screening_rejects_claims_that_cannot_be_true(track_args, blocked):
    from app.music.screening import screen

    assert (screen(_pt(**track_args), today=date(2026, 10, 13)) is not None) is blocked


@pytest.mark.parametrize(("title", "album", "blocked"), [
    # Real re-uploads seen on open-upload platforms.
    ("Naatu Naatu Song from (RRR) Telugu Version", None, True),
    ("Naatu Naatu Song (Telugu)_ RRR Songs NTR,Ram Charan _ MM Keeravani", None, True),
    ("Dakko Dakko Meka song (from pushpa telugu)", None, True),
    ("Butta Bomma Full Video Song", None, True),
    ("Kesariya Lyrical", None, True),
    # Legitimate open uploads must pass.
    ("Friends", "Hindi Christian Songs", False),
    ("Film Noir", "Late Night Jazz", False),
    ("Picture Perfect", None, False),
    ("Suprabhatam", "Melukolupu Patalu", False),
])
def test_screening_film_songs_on_open_upload_platforms(title, album, blocked):
    from app.music.screening import screen

    assert (screen(_pt(title, album=album), open_uploads=True) is not None) is blocked


def test_film_naming_is_trusted_on_curated_platforms():
    from app.music.screening import screen

    # Jamendo / ccMixter artists upload their own work: "(From My Short Film)" is just a title there.
    assert screen(_pt("Theme (From My Short Film)"), open_uploads=False) is None
    platform = _pt("Late Night Drive")
    platform.license = PLATFORM_STREAM_ONLY
    assert screen(platform, open_uploads=True) is None


def test_token_bucket_spaces_requests():
    bucket = TokenBucket(rate=20, burst=1)
    assert bucket.acquire(0) is True
    assert bucket.acquire(0) is False  # empty, and not allowed to wait
    start = time.monotonic()
    assert bucket.acquire(1) is True
    assert time.monotonic() - start >= 0.03

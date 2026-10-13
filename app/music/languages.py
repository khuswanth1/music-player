"""Language catalog and normalization.

Codes are ISO 639-1 where one exists, otherwise ISO 639-3 (e.g. Konkani `kok`, Cantonese `yue`).
`zxx` (ISO 639-2 "no linguistic content") marks instrumental tracks.

Providers report language in many shapes ("tel", "Telugu", "te-IN", "pt_BR"); `normalize()` maps them
all to one code, and returns None rather than guessing when the value is unrecognized.
"""

import re
import unicodedata
from dataclasses import dataclass

INSTRUMENTAL = "zxx"

REGIONS: dict[str, str] = {
    "global": "Global",
    "south-asia": "South Asia",
    "east-asia": "East Asia",
    "southeast-asia": "Southeast Asia",
    "central-asia": "Central Asia & Caucasus",
    "middle-east": "Middle East & North Africa",
    "africa": "Sub-Saharan Africa",
    "europe": "Europe",
    "latin-america": "Latin America & Caribbean",
    "north-america": "North America",
    "oceania": "Oceania",
}


@dataclass(frozen=True)
class Language:
    code: str
    iso639_3: str
    name: str
    native_name: str
    region: str
    rtl: bool = False


def _L(code: str, iso3: str, name: str, native: str, region: str, rtl: bool = False) -> Language:
    return Language(code, iso3, name, native, region, rtl)


LANGUAGES: tuple[Language, ...] = (
    # --- ISO 639-1 -----------------------------------------------------------------------------
    _L("aa", "aar", "Afar", "Qafaraf", "africa"),
    _L("ab", "abk", "Abkhazian", "аԥсуа бызшәа", "central-asia"),
    _L("ae", "ave", "Avestan", "avesta", "central-asia"),
    _L("af", "afr", "Afrikaans", "Afrikaans", "africa"),
    _L("ak", "aka", "Akan", "Akan", "africa"),
    _L("am", "amh", "Amharic", "አማርኛ", "africa"),
    _L("an", "arg", "Aragonese", "aragonés", "europe"),
    _L("ar", "ara", "Arabic", "العربية", "middle-east", True),
    _L("as", "asm", "Assamese", "অসমীয়া", "south-asia"),
    _L("av", "ava", "Avaric", "авар мацӀ", "central-asia"),
    _L("ay", "aym", "Aymara", "aymar aru", "latin-america"),
    _L("az", "aze", "Azerbaijani", "azərbaycan dili", "central-asia"),
    _L("ba", "bak", "Bashkir", "башҡорт теле", "europe"),
    _L("be", "bel", "Belarusian", "беларуская мова", "europe"),
    _L("bg", "bul", "Bulgarian", "български", "europe"),
    _L("bi", "bis", "Bislama", "Bislama", "oceania"),
    _L("bm", "bam", "Bambara", "bamanankan", "africa"),
    _L("bn", "ben", "Bengali", "বাংলা", "south-asia"),
    _L("bo", "bod", "Tibetan", "བོད་ཡིག", "east-asia"),
    _L("br", "bre", "Breton", "brezhoneg", "europe"),
    _L("bs", "bos", "Bosnian", "bosanski", "europe"),
    _L("ca", "cat", "Catalan", "català", "europe"),
    _L("ce", "che", "Chechen", "нохчийн мотт", "central-asia"),
    _L("ch", "cha", "Chamorro", "Chamoru", "oceania"),
    _L("co", "cos", "Corsican", "corsu", "europe"),
    _L("cr", "cre", "Cree", "ᓀᐦᐃᔭᐍᐏᐣ", "north-america"),
    _L("cs", "ces", "Czech", "čeština", "europe"),
    _L("cu", "chu", "Church Slavonic", "ѩзыкъ словѣньскъ", "europe"),
    _L("cv", "chv", "Chuvash", "чӑваш чӗлхи", "europe"),
    _L("cy", "cym", "Welsh", "Cymraeg", "europe"),
    _L("da", "dan", "Danish", "dansk", "europe"),
    _L("de", "deu", "German", "Deutsch", "europe"),
    _L("dv", "div", "Divehi", "ދިވެހި", "south-asia", True),
    _L("dz", "dzo", "Dzongkha", "རྫོང་ཁ", "south-asia"),
    _L("ee", "ewe", "Ewe", "Eʋegbe", "africa"),
    _L("el", "ell", "Greek", "Ελληνικά", "europe"),
    _L("en", "eng", "English", "English", "global"),
    _L("eo", "epo", "Esperanto", "Esperanto", "global"),
    _L("es", "spa", "Spanish", "Español", "latin-america"),
    _L("et", "est", "Estonian", "eesti", "europe"),
    _L("eu", "eus", "Basque", "euskara", "europe"),
    _L("fa", "fas", "Persian", "فارسی", "middle-east", True),
    _L("ff", "ful", "Fula", "Fulfulde", "africa"),
    _L("fi", "fin", "Finnish", "suomi", "europe"),
    _L("fj", "fij", "Fijian", "vosa Vakaviti", "oceania"),
    _L("fo", "fao", "Faroese", "føroyskt", "europe"),
    _L("fr", "fra", "French", "Français", "europe"),
    _L("fy", "fry", "Western Frisian", "Frysk", "europe"),
    _L("ga", "gle", "Irish", "Gaeilge", "europe"),
    _L("gd", "gla", "Scottish Gaelic", "Gàidhlig", "europe"),
    _L("gl", "glg", "Galician", "galego", "europe"),
    _L("gn", "grn", "Guarani", "Avañe'ẽ", "latin-america"),
    _L("gu", "guj", "Gujarati", "ગુજરાતી", "south-asia"),
    _L("gv", "glv", "Manx", "Gaelg", "europe"),
    _L("ha", "hau", "Hausa", "Hausa", "africa"),
    _L("he", "heb", "Hebrew", "עברית", "middle-east", True),
    _L("hi", "hin", "Hindi", "हिन्दी", "south-asia"),
    _L("ho", "hmo", "Hiri Motu", "Hiri Motu", "oceania"),
    _L("hr", "hrv", "Croatian", "hrvatski", "europe"),
    _L("ht", "hat", "Haitian Creole", "Kreyòl ayisyen", "latin-america"),
    _L("hu", "hun", "Hungarian", "magyar", "europe"),
    _L("hy", "hye", "Armenian", "Հայերեն", "central-asia"),
    _L("hz", "her", "Herero", "Otjiherero", "africa"),
    _L("ia", "ina", "Interlingua", "Interlingua", "global"),
    _L("id", "ind", "Indonesian", "Bahasa Indonesia", "southeast-asia"),
    _L("ie", "ile", "Interlingue", "Interlingue", "global"),
    _L("ig", "ibo", "Igbo", "Asụsụ Igbo", "africa"),
    _L("ii", "iii", "Nuosu", "ꆈꌠ꒿", "east-asia"),
    _L("ik", "ipk", "Inupiaq", "Iñupiaq", "north-america"),
    _L("io", "ido", "Ido", "Ido", "global"),
    _L("is", "isl", "Icelandic", "Íslenska", "europe"),
    _L("it", "ita", "Italian", "Italiano", "europe"),
    _L("iu", "iku", "Inuktitut", "ᐃᓄᒃᑎᑐᑦ", "north-america"),
    _L("ja", "jpn", "Japanese", "日本語", "east-asia"),
    _L("jv", "jav", "Javanese", "basa Jawa", "southeast-asia"),
    _L("ka", "kat", "Georgian", "ქართული", "central-asia"),
    _L("kg", "kon", "Kongo", "Kikongo", "africa"),
    _L("ki", "kik", "Kikuyu", "Gĩkũyũ", "africa"),
    _L("kj", "kua", "Kwanyama", "Kuanyama", "africa"),
    _L("kk", "kaz", "Kazakh", "қазақ тілі", "central-asia"),
    _L("kl", "kal", "Greenlandic", "kalaallisut", "north-america"),
    _L("km", "khm", "Khmer", "ខ្មែរ", "southeast-asia"),
    _L("kn", "kan", "Kannada", "ಕನ್ನಡ", "south-asia"),
    _L("ko", "kor", "Korean", "한국어", "east-asia"),
    _L("kr", "kau", "Kanuri", "Kanuri", "africa"),
    _L("ks", "kas", "Kashmiri", "कॉशुर", "south-asia"),
    _L("ku", "kur", "Kurdish", "Kurdî", "middle-east"),
    _L("kv", "kom", "Komi", "коми кыв", "europe"),
    _L("kw", "cor", "Cornish", "Kernewek", "europe"),
    _L("ky", "kir", "Kyrgyz", "Кыргызча", "central-asia"),
    _L("la", "lat", "Latin", "Latina", "global"),
    _L("lb", "ltz", "Luxembourgish", "Lëtzebuergesch", "europe"),
    _L("lg", "lug", "Ganda", "Luganda", "africa"),
    _L("li", "lim", "Limburgish", "Limburgs", "europe"),
    _L("ln", "lin", "Lingala", "Lingála", "africa"),
    _L("lo", "lao", "Lao", "ພາສາລາວ", "southeast-asia"),
    _L("lt", "lit", "Lithuanian", "lietuvių", "europe"),
    _L("lu", "lub", "Luba-Katanga", "Kiluba", "africa"),
    _L("lv", "lav", "Latvian", "latviešu", "europe"),
    _L("mg", "mlg", "Malagasy", "fiteny malagasy", "africa"),
    _L("mh", "mah", "Marshallese", "Kajin M̧ajeļ", "oceania"),
    _L("mi", "mri", "Māori", "te reo Māori", "oceania"),
    _L("mk", "mkd", "Macedonian", "македонски", "europe"),
    _L("ml", "mal", "Malayalam", "മലയാളം", "south-asia"),
    _L("mn", "mon", "Mongolian", "Монгол хэл", "east-asia"),
    _L("mr", "mar", "Marathi", "मराठी", "south-asia"),
    _L("ms", "msa", "Malay", "Bahasa Melayu", "southeast-asia"),
    _L("mt", "mlt", "Maltese", "Malti", "europe"),
    _L("my", "mya", "Burmese", "မြန်မာစာ", "southeast-asia"),
    _L("na", "nau", "Nauruan", "Dorerin Naoero", "oceania"),
    _L("nb", "nob", "Norwegian Bokmål", "norsk bokmål", "europe"),
    _L("nd", "nde", "Northern Ndebele", "isiNdebele", "africa"),
    _L("ne", "nep", "Nepali", "नेपाली", "south-asia"),
    _L("ng", "ndo", "Ndonga", "Owambo", "africa"),
    _L("nl", "nld", "Dutch", "Nederlands", "europe"),
    _L("nn", "nno", "Norwegian Nynorsk", "norsk nynorsk", "europe"),
    _L("no", "nor", "Norwegian", "norsk", "europe"),
    _L("nr", "nbl", "Southern Ndebele", "isiNdebele", "africa"),
    _L("nv", "nav", "Navajo", "Diné bizaad", "north-america"),
    _L("ny", "nya", "Chichewa", "chiCheŵa", "africa"),
    _L("oc", "oci", "Occitan", "occitan", "europe"),
    _L("oj", "oji", "Ojibwe", "ᐊᓂᔑᓈᐯᒧᐎᓐ", "north-america"),
    _L("om", "orm", "Oromo", "Afaan Oromoo", "africa"),
    _L("or", "ori", "Odia", "ଓଡ଼ିଆ", "south-asia"),
    _L("os", "oss", "Ossetian", "ирон æвзаг", "central-asia"),
    _L("pa", "pan", "Punjabi", "ਪੰਜਾਬੀ", "south-asia"),
    _L("pi", "pli", "Pali", "पालि", "south-asia"),
    _L("pl", "pol", "Polish", "polski", "europe"),
    _L("ps", "pus", "Pashto", "پښتو", "south-asia", True),
    _L("pt", "por", "Portuguese", "Português", "latin-america"),
    _L("qu", "que", "Quechua", "Runa Simi", "latin-america"),
    _L("rm", "roh", "Romansh", "rumantsch", "europe"),
    _L("rn", "run", "Kirundi", "Ikirundi", "africa"),
    _L("ro", "ron", "Romanian", "Română", "europe"),
    _L("ru", "rus", "Russian", "Русский", "europe"),
    _L("rw", "kin", "Kinyarwanda", "Ikinyarwanda", "africa"),
    _L("sa", "san", "Sanskrit", "संस्कृतम्", "south-asia"),
    _L("sc", "srd", "Sardinian", "sardu", "europe"),
    _L("sd", "snd", "Sindhi", "سنڌي", "south-asia", True),
    _L("se", "sme", "Northern Sámi", "davvisámegiella", "europe"),
    _L("sg", "sag", "Sango", "yângâ tî sängö", "africa"),
    _L("si", "sin", "Sinhala", "සිංහල", "south-asia"),
    _L("sk", "slk", "Slovak", "slovenčina", "europe"),
    _L("sl", "slv", "Slovenian", "slovenščina", "europe"),
    _L("sm", "smo", "Samoan", "Gagana Sāmoa", "oceania"),
    _L("sn", "sna", "Shona", "chiShona", "africa"),
    _L("so", "som", "Somali", "Soomaali", "africa"),
    _L("sq", "sqi", "Albanian", "Shqip", "europe"),
    _L("sr", "srp", "Serbian", "српски", "europe"),
    _L("ss", "ssw", "Swati", "siSwati", "africa"),
    _L("st", "sot", "Sesotho", "Sesotho", "africa"),
    _L("su", "sun", "Sundanese", "Basa Sunda", "southeast-asia"),
    _L("sv", "swe", "Swedish", "Svenska", "europe"),
    _L("sw", "swa", "Swahili", "Kiswahili", "africa"),
    _L("ta", "tam", "Tamil", "தமிழ்", "south-asia"),
    _L("te", "tel", "Telugu", "తెలుగు", "south-asia"),
    _L("tg", "tgk", "Tajik", "тоҷикӣ", "central-asia"),
    _L("th", "tha", "Thai", "ไทย", "southeast-asia"),
    _L("ti", "tir", "Tigrinya", "ትግርኛ", "africa"),
    _L("tk", "tuk", "Turkmen", "Türkmençe", "central-asia"),
    _L("tl", "tgl", "Tagalog", "Tagalog", "southeast-asia"),
    _L("tn", "tsn", "Tswana", "Setswana", "africa"),
    _L("to", "ton", "Tongan", "lea faka-Tonga", "oceania"),
    _L("tr", "tur", "Turkish", "Türkçe", "middle-east"),
    _L("ts", "tso", "Tsonga", "Xitsonga", "africa"),
    _L("tt", "tat", "Tatar", "татар теле", "europe"),
    _L("tw", "twi", "Twi", "Twi", "africa"),
    _L("ty", "tah", "Tahitian", "Reo Tahiti", "oceania"),
    _L("ug", "uig", "Uyghur", "ئۇيغۇرچە", "east-asia", True),
    _L("uk", "ukr", "Ukrainian", "Українська", "europe"),
    _L("ur", "urd", "Urdu", "اردو", "south-asia", True),
    _L("uz", "uzb", "Uzbek", "Oʻzbekcha", "central-asia"),
    _L("ve", "ven", "Venda", "Tshivenḓa", "africa"),
    _L("vi", "vie", "Vietnamese", "Tiếng Việt", "southeast-asia"),
    _L("vo", "vol", "Volapük", "Volapük", "global"),
    _L("wa", "wln", "Walloon", "walon", "europe"),
    _L("wo", "wol", "Wolof", "Wolof", "africa"),
    _L("xh", "xho", "Xhosa", "isiXhosa", "africa"),
    _L("yi", "yid", "Yiddish", "ייִדיש", "europe", True),
    _L("yo", "yor", "Yoruba", "Yorùbá", "africa"),
    _L("za", "zha", "Zhuang", "Saɯ cueŋƅ", "east-asia"),
    _L("zh", "zho", "Chinese", "中文", "east-asia"),
    _L("zu", "zul", "Zulu", "isiZulu", "africa"),
    # --- widely sung languages without an ISO 639-1 code (ISO 639-3) ---------------------------
    _L("awa", "awa", "Awadhi", "अवधी", "south-asia"),
    _L("bgc", "bgc", "Haryanvi", "हरियाणवी", "south-asia"),
    _L("bho", "bho", "Bhojpuri", "भोजपुरी", "south-asia"),
    _L("brx", "brx", "Bodo", "बड़ो", "south-asia"),
    _L("ceb", "ceb", "Cebuano", "Binisaya", "southeast-asia"),
    _L("doi", "doi", "Dogri", "डोगरी", "south-asia"),
    _L("fil", "fil", "Filipino", "Filipino", "southeast-asia"),
    _L("haw", "haw", "Hawaiian", "ʻŌlelo Hawaiʻi", "oceania"),
    _L("hmn", "hmn", "Hmong", "Hmoob", "southeast-asia"),
    _L("hne", "hne", "Chhattisgarhi", "छत्तीसगढ़ी", "south-asia"),
    _L("kok", "kok", "Konkani", "कोंकणी", "south-asia"),
    _L("mai", "mai", "Maithili", "मैथिली", "south-asia"),
    _L("mni", "mni", "Manipuri (Meitei)", "ꯃꯤꯇꯩꯂꯣꯟ", "south-asia"),
    _L("nan", "nan", "Hokkien", "閩南語", "east-asia"),
    _L("pcm", "pcm", "Nigerian Pidgin", "Naijá", "africa"),
    _L("raj", "raj", "Rajasthani", "राजस्थानी", "south-asia"),
    _L("sat", "sat", "Santali", "ᱥᱟᱱᱛᱟᱲᱤ", "south-asia"),
    _L("tcy", "tcy", "Tulu", "ತುಳು", "south-asia"),
    _L("yue", "yue", "Cantonese", "粵語", "east-asia"),
    # --- no linguistic content ------------------------------------------------------------------
    _L(INSTRUMENTAL, "zxx", "Instrumental", "Instrumental", "global"),
)

# Shown first in pickers and on the languages page.
FEATURED = ("te", "hi", "ta", "kn", "ml", "bn", "pa", "mr", "gu", "ur", "en", "ko", "ja", "zh", "ar", "es", "fr",
            "pt", "de", "ru", "it", "tr", "id", "sw", "yo", INSTRUMENTAL)

BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}

# ISO 639-2/B bibliographic codes and common names that differ from the catalog's own spellings.
_ALIASES = {
    "alb": "sq", "arm": "hy", "baq": "eu", "bur": "my", "chi": "zh", "cze": "cs", "dut": "nl", "fre": "fr",
    "geo": "ka", "ger": "de", "gre": "el", "ice": "is", "mac": "mk", "mao": "mi", "may": "ms", "per": "fa",
    "rum": "ro", "slo": "sk", "tib": "bo", "wel": "cy", "cmn": "zh", "zhs": "zh", "zht": "zh", "iw": "he", "in": "id",
    "ji": "yi", "jw": "jv", "mo": "ro", "sh": "sr", "tgl": "tl", "pes": "fa", "prs": "fa", "arb": "ar",
    "farsi": "fa", "panjabi": "pa", "oriya": "or", "castilian": "es", "mandarin": "zh", "putonghua": "zh",
    "moldavian": "ro", "moldovan": "ro", "flemish": "nl", "gaelic": "gd", "bangla": "bn", "burmese": "my",
    "kiswahili": "sw", "persian": "fa", "brazilian portuguese": "pt", "valencian": "ca", "slovene": "sl",
    "hebrew": "he", "malay": "ms", "instrumental": INSTRUMENTAL, "no linguistic content": INSTRUMENTAL,
    "no lyrics": INSTRUMENTAL, "meitei": "mni", "meithei": "mni", "odiya": "or", "kanarese": "kn",
    "telegu": "te", "tamizh": "ta", "hindustani": "hi", "deutsch": "de", "espanol": "es", "francais": "fr",
    "nihongo": "ja", "hangul": "ko", "hangugeo": "ko", "zhongwen": "zh", "russkiy": "ru",
}

_LOOKUP: dict[str, str] = {}
for _lang in LANGUAGES:
    _LOOKUP[_lang.code] = _lang.code
    _LOOKUP[_lang.iso639_3] = _lang.code
    _LOOKUP[_lang.name.lower()] = _lang.code
    _LOOKUP[unicodedata.normalize("NFKC", _lang.native_name).casefold()] = _lang.code
_LOOKUP.update(_ALIASES)


def normalize(value: str | None) -> str | None:
    """Map a provider's language value to a catalog code, or None if it isn't recognized.

    Accepts ISO 639-1/2/3 codes, BCP 47 tags ("te-IN", "zh_Hant"), English and native names.
    A list ("tel; eng") resolves to its first recognized entry.
    """
    if not value:
        return None
    for part in re.split(r"[;,/|]| and ", str(value)):
        key = unicodedata.normalize("NFKC", part).strip().casefold()
        if not key:
            continue
        key = re.sub(r"\s*\(.*\)$", "", key)  # "Greek (modern)" -> "greek"
        key = re.sub(r"\s+language$", "", key)
        if key in _LOOKUP:
            return _LOOKUP[key]
        primary = re.split(r"[-_]", key, maxsplit=1)[0]  # BCP 47 primary subtag
        if primary in _LOOKUP and len(primary) in (2, 3):
            return _LOOKUP[primary]
    return None


# Scripts used (for practical purposes) by exactly one catalog language. Ambiguous scripts such as
# Devanagari, Arabic, Cyrillic, Bengali or Han are deliberately absent: we never guess between languages.
_SCRIPT_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x0530, 0x058F, "hy"),  # Armenian
    (0x0780, 0x07BF, "dv"),  # Thaana
    (0x0A00, 0x0A7F, "pa"),  # Gurmukhi
    (0x0A80, 0x0AFF, "gu"),  # Gujarati
    (0x0B00, 0x0B7F, "or"),  # Odia
    (0x0B80, 0x0BFF, "ta"),  # Tamil
    (0x0C00, 0x0C7F, "te"),  # Telugu
    (0x0C80, 0x0CFF, "kn"),  # Kannada
    (0x0D00, 0x0D7F, "ml"),  # Malayalam
    (0x0D80, 0x0DFF, "si"),  # Sinhala
    (0x0E00, 0x0E7F, "th"),  # Thai
    (0x0E80, 0x0EFF, "lo"),  # Lao
    (0x1000, 0x109F, "my"),  # Myanmar
    (0x10A0, 0x10FF, "ka"),  # Georgian
    (0x1100, 0x11FF, "ko"),  # Hangul Jamo
    (0x1780, 0x17FF, "km"),  # Khmer
    (0x1C50, 0x1C7F, "sat"),  # Ol Chiki
    (0x3040, 0x30FF, "ja"),  # Hiragana + Katakana
    (0x3130, 0x318F, "ko"),  # Hangul compatibility Jamo
    (0xABC0, 0xABFF, "mni"),  # Meetei Mayek
    (0xAC00, 0xD7AF, "ko"),  # Hangul syllables
)


def _script_language(ch: str) -> str | None:
    cp = ord(ch)
    for lo, hi, code in _SCRIPT_RANGES:
        if lo <= cp <= hi:
            return code
    return None


def detect_from_script(*texts: str | None) -> str | None:
    """Infer a language from writing systems that map to a single language (e.g. Telugu script → te).

    Requires at least two letters in that script, making up most of the non-Latin letters, so a stray
    symbol never decides. Japanese wins over Han characters when kana is present.
    """
    counts: dict[str, int] = {}
    other = 0
    for text in texts:
        for ch in text or "":
            if not ch.isalpha() or ord(ch) < 0x0250:  # skip Latin, digits, punctuation
                continue
            code = _script_language(ch)
            if code:
                counts[code] = counts.get(code, 0) + 1
            elif not ("一" <= ch <= "鿿"):  # Han is neutral (shared by zh/ja)
                other += 1
    if not counts:
        return None
    code, n = max(counts.items(), key=lambda kv: kv[1])
    return code if n >= 2 and n > other else None

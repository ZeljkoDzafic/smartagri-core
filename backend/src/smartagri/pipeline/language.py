"""Language of a chat message (spec 017, section "Jezik razgovora / chat language").

The AI chat answers in the language of the user's message, independently of the interface locale. This module is
the cheap deterministic first step: it never calls a model. It looks at the script of the letters and, inside a
script, at letters and function words that tell languages apart:

- Cyrillic: the local alphabet (Serbian Cyrillic, 30 letters) has neither й щ ъ ь ы э ю я ё nor є і ї ґ ў, so any of
  them means Russian, Ukrainian, Belarusian or Bulgarian; ѓ ќ ѕ mean Macedonian; ђ ћ mean the local language.
  Without such letters (ј љ њ џ are shared with Macedonian) word lists decide.
- Latin: đ and local function words against letter sets and function words of English, German, Hungarian,
  Slovenian, Romanian, Albanian, Polish, Czech, Slovak, Italian, Spanish, French, Portuguese, Dutch and Turkish.
- Other scripts (Arabic, Greek, Hebrew, Armenian, Georgian, Devanagari, Thai, Hangul, Kana, Han): the script.

Rules (documented choices, not measured accuracy):
- No evidence at all (e.g. "x", "NDVI?") → method "default": the caller lets the interface locale decide.
- A tie between local and foreign evidence (e.g. Slovenian "Kako je koruza?") → local. Slovenian shares č š ž and
  many words with the local language; only distinctive Slovenian words (kdaj, naj, kaj, tudi, ...) count for it.
- `confident` is False when the evidence is thin; the caller then lets the pivot model call name the language.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

LOCAL_BASES = {"sr", "hr", "bs", "cnr", "sh"}

NAMES = {
    "en": "English", "de": "German", "hu": "Hungarian", "sl": "Slovenian", "ro": "Romanian", "sq": "Albanian",
    "pl": "Polish", "cs": "Czech", "sk": "Slovak", "it": "Italian", "es": "Spanish", "fr": "French", "pt": "Portuguese",
    "nl": "Dutch", "tr": "Turkish", "ru": "Russian", "uk": "Ukrainian", "be": "Belarusian", "bg": "Bulgarian",
    "mk": "Macedonian", "ar": "Arabic", "fa": "Persian", "ur": "Urdu", "el": "Greek", "he": "Hebrew", "hy": "Armenian",
    "ka": "Georgian", "hi": "Hindi", "bn": "Bengali", "th": "Thai", "ko": "Korean", "ja": "Japanese", "zh": "Chinese",
}
# Neutral names for the local language (no national name in anything a user may see; spec 017 US4).
LOCAL_NAMES = {"Latn": "Lokalni (latinica)", "Cyrl": "Локални (ћирилица)"}


def is_local(code: Optional[str]) -> bool:
    return bool(code) and str(code).replace("_", "-").split("-")[0].lower() in LOCAL_BASES


@dataclass
class Detection:
    code: str                 # BCP 47: "sr-Latn" / "sr-Cyrl" for the local language, else e.g. "de", "ru", "ar"
    name: str
    method: str               # "script" | "markers" | "default" | "llm"
    local: bool
    script: str               # "Latn", "Cyrl", "Arab", ...
    confident: bool

    def record(self) -> Dict[str, object]:
        """The `language` record of the answer and the run: {detected, name, method, local, script}."""
        d = asdict(self)
        return {"detected": d["code"], "name": d["name"], "method": d["method"], "local": d["local"],
                "script": d["script"]}


# ---------------------------------------------------------------- scripts
SCRIPTS: List[Tuple[str, List[Tuple[int, int]]]] = [
    ("Latn", [(0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x24F), (0x1E00, 0x1EFF)]),
    ("Cyrl", [(0x400, 0x52F)]),
    ("Arab", [(0x600, 0x6FF), (0x750, 0x77F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)]),
    ("Grek", [(0x370, 0x3FF), (0x1F00, 0x1FFF)]),
    ("Hebr", [(0x590, 0x5FF)]),
    ("Armn", [(0x530, 0x58F)]),
    ("Geor", [(0x10A0, 0x10FF)]),
    ("Deva", [(0x900, 0x97F)]),
    ("Beng", [(0x980, 0x9FF)]),
    ("Thai", [(0xE00, 0xE7F)]),
    ("Hang", [(0x1100, 0x11FF), (0xAC00, 0xD7AF)]),
    ("Kana", [(0x3040, 0x30FF)]),
    ("Hani", [(0x4E00, 0x9FFF)]),
]
SCRIPT_LANG = {"Grek": ("el", True), "Hebr": ("he", True), "Armn": ("hy", True), "Geor": ("ka", True),
               "Deva": ("hi", False), "Beng": ("bn", False), "Thai": ("th", True), "Hang": ("ko", True),
               "Kana": ("ja", True), "Hani": ("zh", False)}


def _script(ch: str) -> Optional[str]:
    o = ord(ch)
    for name, ranges in SCRIPTS:
        for lo, hi in ranges:
            if lo <= o <= hi:
                return name
    return None


def script_counts(text: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for ch in text:
        if ch.isalpha():
            s = _script(ch)
            if s:
                out[s] = out.get(s, 0) + 1
    return out


WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")


def _words(text: str) -> List[str]:
    return [w.lower() for w in WORD.findall(text)]


# ---------------------------------------------------------------- Latin script
# Local function and domain words (Latin; ekavian and ijekavian forms, with and without diacritics).
LOCAL_WORDS = set("""da li je se u i na za od do sa iz kako kada kad sta šta sto što koji koja koje kojim koliko gde
gdje zasto zašto treba trebam mogu moze može ima nema ovo ovaj ova ovde ovdje sada sad sutra danas juce jučer juče
posle poslije toga onda jos još vec već ali ili jer ako bi bih mi moj moja moje nasa naša kukuruz kukuruza kukuruzu
njiva njivi njive parcela parceli parcele usev usjev useva usjeva navodnjavam navodnjavati navodnjavanje navodnjavanja
zalivati zalijevati prskati prskanje djubrivo đubrivo dubrenje đubrenje gnojivo prihrana prihranu azot azota dušik
kisa kiša kise kiše zemljiste zemljište vlaga vlage setva sjetva berba žetva zetva biljke biljka list lisce lišće bolest
stetocine štetočine izgleda dobro lose loše molim hvala to ta taj ti o""".split())
LOCAL_LETTERS = {"đ": 2, "ć": 1, "č": 1, "š": 1, "ž": 1}
# Distinctive words only: words shared with the local language are left out on purpose (see the module docstring).
FOREIGN: Dict[str, Tuple[str, str]] = {
    "en": ("", """the is are was what when how should could would can my your our this that with for from about
          water watering irrigate irrigation field fields maize corn crop crops rain fertilizer fertiliser nitrogen
          do does did have has need much many which why where during after before now today tomorrow yes please
          thanks hello it they we you there their soil plants leaves disease weather spray spraying"""),
    "de": ("äöüß", """der die das und ist nicht ich ein eine einen wann soll sollte muss mein meine meinen den dem
          wie was wir mit auf für heute morgen regen dünger bewässern bewässerung feld mais pflanzen boden wasser
          es gibt habe hat bitte danke"""),
    "hu": ("őűáéíóöüú", """és az hogy mikor kell nem vagy van egy kukorica kukoricát kukoricám öntözni öntözés mit
          hogyan ezt ezen meg már még holnap ma eső műtrágya talaj"""),
    "sl": ("", """kdaj naj kaj ki sem bi lahko zelo koruza koruzo koruze zalivati zalivam zalivanje tudi vendar če
          ker kje kdo moram moja tej ta to tem dež jutri danes gnojiti gnojenje njivo zemlja"""),
    "ro": ("ăâîșțşţ", """și să este nu când cum porumb porumbul irigare iriga trebuie pentru cu în mâine azi ploaie
          îngrășământ"""),
    "sq": ("ëç", """dhe një është të në për si kur duhet misri misër ujit ujitje nesër sot shi pleh"""),
    "pl": ("ąęłńśźżó", """jak kiedy czy nie jest się kukurydza kukurydzę podlewać mam moje jutro dzisiaj deszcz
          nawóz"""),
    "cs": ("řěůý", """jak kdy kukuřice kukuřici zalévat mám bych zítra dnes déšť hnojivo"""),
    "sk": ("ľĺŕôäý", """kedy kukurica kukuricu zalievať mám som zajtra dnes dážď hnojivo"""),
    "it": ("àèìòù", """il di che quando come irrigare devo non è sono per con domani oggi pioggia concime"""),
    "es": ("ñ¿¡áéíóú", """el la de que cuando cómo maíz regar debo es por para con mañana hoy lluvia abono"""),
    "fr": ("çéèêàùûôîïœ", """le la les de des que quand comment maïs irriguer dois je ne pas est pour avec demain
          aujourd'hui pluie engrais"""),
    "pt": ("ãõçáéíóúâêô", """o de que quando como milho regar devo não é para com amanhã hoje chuva adubo"""),
    "nl": ("", """het een en wanneer hoe moet ik niet irrigeren van morgen vandaag regen mest"""),
    "tr": ("ğışİçöü", """ve bir ne zaman nasıl mısır sulama mı mi bu için yarın bugün yağmur gübre"""),
}
# Spec 036 FR-016 (additive): more function and farm words for the languages of the new interface locales.
# Written by the developer, not by native speakers; accuracy is not measured yet (T021, SC-007).
FOREIGN_EXTRA = {
    "hu": "nekem milyen mennyi szeretném tudni lehet kellene földem táblám permetezni trágyázni vetés aratás",
    "ro": "care unde câtă cât trebuie să pot vreau meu mea câmpul solul fertilizare stropire semănat recoltare",
    "sl": "zdaj koliko vode moram lahko mojo moja njiva škropiti gnojilo setev žetev",
    "sq": "sa duhet të mund dua tokën fushën plehërim spërkatje mbjellje korrje është",
    "de": "wieviel wieviele sollte ich kann meine düngen spritzen aussaat ernte acker gießen",
    "tr": "ne kadar gerekir yapmalıyım tarlamı gübreleme ilaçlama ekim hasat toprak sulamalı",
    "fr": "combien faut-il puis mon ma champ sol engrais pulvériser semis récolte arroser",
    "it": "quanto quanta devo posso mio mia campo terreno concimare irrorare semina raccolto acqua",
    "es": "cuánto cuánta debo puedo mi campo suelo abonar fumigar siembra cosecha agua",
    "pt": "quanto quanta devo posso meu minha campo solo adubar pulverizar sementeira colheita água",
    "pl": "ile powinienem mogę moje pole gleba nawożenie opryskiwanie siew zbiór wody",
}
for _k, _w in FOREIGN_EXTRA.items():
    FOREIGN[_k] = (FOREIGN[_k][0], FOREIGN[_k][1] + " " + _w)
FOREIGN_WORDS = {k: set(v[1].split()) for k, v in FOREIGN.items()}
FOREIGN_LETTERS = {k: set(v[0]) for k, v in FOREIGN.items()}
# Words of a foreign list that are also local words never count for the foreign language.
for _k in FOREIGN_WORDS:
    FOREIGN_WORDS[_k] -= LOCAL_WORDS

# ---------------------------------------------------------------- Cyrillic script
CYR_LOCAL_ONLY = set("ђћЂЋ")
CYR_MK_ONLY = set("ѓќѕЃЌЅ")
CYR_NOT_LOCAL = set("йщъьыэюяёєіїґўЙЩЪЬЫЭЮЯЁЄІЇҐЎ")
CYR_LOCAL_WORDS = set("""да ли је се у и на за од до са из како када кад шта што који која које колико где зашто
треба могу може има нема ово овај ова сада сутра данас после поново још већ али или јер ако мој моја моје кукуруз
кукуруза кукурузу њива њиви парцела парцели усев усева наводњавам наводњавати наводњавање ђубриво прихрана азот
азота киша кише земљиште влага сетва берба биљке болест изгледа добро лоше молим хвала или то""".split())
CYR_FOREIGN_WORDS = {
    "mk": set("""што кога дали јас сум ќе во со го ги пченка пченката наводнување наводнувам треба нива денес утре
              дожд ѓубриво правам сакам нивата водата земјата дождот полето""".split()),
    "ru": set("""что как когда это нужно надо мне мой моя поле кукуруза кукурузу поливать полив полить дождь
              удобрение сегодня завтра почва привет спасибо пожалуйста или""".split()),
    "uk": set("""що як коли це потрібно треба мені мій моя поле кукурудза кукурудзу поливати дощ добриво сьогодні
              завтра ґрунт дякую будь""".split()),
    "bg": set("""какво как кога това трябва ми моя поле царевица царевицата поливам поливане дъжд тор днес утре
              почва благодаря моля""".split()),
    "be": set("""што як калі гэта трэба мне мой мая поле кукуруза паліваць дождж""".split()),
}
# Spec 036 FR-016 (additive): Bulgarian has no letters that tell it from Russian beyond ъ in some positions, so
# function words decide; Macedonian and Ukrainian get more words too.
CYR_FOREIGN_WORDS["bg"] |= set("""кога трябва ли колко нивата нивата ми поливане торене пръскане сеитба жътва ще съм е""".split())
CYR_FOREIGN_WORDS["mk"] |= set("""колку кога треба нивата ѓубрење прскање сеидба жетва ли да""".split()) - {"да", "ли"}
CYR_FOREIGN_WORDS["uk"] |= set("""скільки чи можна моє поле добрива обприскування посів збирання води""".split())
CYR_FOREIGN_WORDS["ru"] |= set("""сколько можно моё поле удобрения опрыскивание посев уборка воды ли""".split()) - {"ли"}
for _k in CYR_FOREIGN_WORDS:
    CYR_FOREIGN_WORDS[_k] -= CYR_LOCAL_WORDS


def _local(script: str, method: str, confident: bool) -> Detection:
    return Detection("sr-Cyrl" if script == "Cyrl" else "sr-Latn", LOCAL_NAMES["Cyrl" if script == "Cyrl" else "Latn"],
                     method, True, script, confident)


def _foreign(code: str, script: str, method: str, confident: bool) -> Detection:
    return Detection(code, NAMES.get(code, code), method, False, script, confident)


def _best(scores: Dict[str, int]) -> Tuple[Optional[str], int, int]:
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] == 0:
        return None, 0, 0
    return ranked[0][0], ranked[0][1], ranked[1][1] if len(ranked) > 1 else 0


def _detect_cyrillic(text: str, words: List[str]) -> Detection:
    letters = set(text)
    if letters & CYR_MK_ONLY:
        return _foreign("mk", "Cyrl", "markers", True)
    if letters & CYR_NOT_LOCAL:
        low = letters
        if low & set("єїґЄЇҐ"):
            return _foreign("uk", "Cyrl", "markers", True)
        if low & set("ўЎ"):
            return _foreign("be", "Cyrl", "markers", True)
        if low & set("ыэёЫЭЁ"):
            return _foreign("ru", "Cyrl", "markers", True)
        if low & set("іІ"):
            # spec 036: і is Ukrainian or Belarusian; Ukrainian words make it confident
            uk_words = sum(1 for w in words if w in CYR_FOREIGN_WORDS["uk"])
            return _foreign("uk", "Cyrl", "markers", uk_words >= 2)
        scores = {k: sum(1 for w in words if w in v) for k, v in CYR_FOREIGN_WORDS.items() if k in ("ru", "bg", "uk")}
        if "ъ" in low or "Ъ" in low:
            scores["bg"] = scores.get("bg", 0) + 2
        best, top, second = _best(scores)
        if best is None:
            return _foreign("ru", "Cyrl", "markers", False)
        return _foreign(best, "Cyrl", "markers", top - second >= 1)
    if letters & CYR_LOCAL_ONLY:
        return _local("Cyrl", "markers", True)
    local = sum(1 for w in words if w in CYR_LOCAL_WORDS)
    scores = {k: sum(1 for w in words if w in v) for k, v in CYR_FOREIGN_WORDS.items()}
    best, top, second = _best(scores)
    if best is None or local >= top:
        if local == 0 and best is None:
            return _local("Cyrl", "default", False)
        return _local("Cyrl", "markers", local > top)
    return _foreign(best, "Cyrl", "markers", top - max(second, local) >= 1)


def _detect_latin(text: str, words: List[str]) -> Detection:
    low = text.lower()
    local = sum(1 for w in words if w in LOCAL_WORDS) + sum(v for k, v in LOCAL_LETTERS.items() if k in low)
    scores: Dict[str, int] = {}
    for code in FOREIGN:
        letters = sum(1 for ch in FOREIGN_LETTERS[code] if ch in low)
        scores[code] = letters + sum(1 for w in words if w in FOREIGN_WORDS[code])
    best, top, second = _best(scores)
    if best is None:
        return _local("Latn", "markers" if local else "default", local > 0)
    if local >= top:                                     # ties go to the local language (documented)
        return _local("Latn", "markers", local > top)
    return _foreign(best, "Latn", "markers", top >= 2 and top - max(second, local) >= 1)


def detect(text: str) -> Detection:
    """Deterministic language detection of a chat message (see the module docstring)."""
    counts = script_counts(text or "")
    if not counts:
        return _local("Latn", "default", False)
    script = max(sorted(counts), key=lambda s: counts[s])
    words = _words(text)
    if script == "Cyrl":
        return _detect_cyrillic(text, words)
    if script == "Latn":
        return _detect_latin(text, words)
    if script == "Arab":
        if set(text) & set("ٹڈڑںے"):
            return _foreign("ur", script, "script", True)
        if set(text) & set("پچژگ"):
            return _foreign("fa", script, "script", False)
        return _foreign("ar", script, "script", False)
    if script == "Hani" and counts.get("Kana"):
        script = "Kana"
    code, confident = SCRIPT_LANG.get(script, ("und", False))
    return _foreign(code, script, "script", confident)


# ---------------------------------------------------------------- numbers, units, doses (language-agnostic gate)
# Spec 036 FR-016: bidi control characters (LRM, RLM, LRE..RLO, LRI..PDI, ALM) carry no meaning for the gate and are
# removed before numbers and units are compared, so an isolated value in a right-to-left text still matches.
BIDI_CONTROLS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069\u061c]")


def strip_bidi(text: str) -> str:
    return BIDI_CONTROLS.sub("", text or "")


def ascii_digits(text: str) -> str:
    """Every decimal digit of any script (Eastern Arabic, Persian, Devanagari, ...) as 0-9; Arabic separators too."""
    out = []
    for ch in strip_bidi(text):
        if ch.isdigit() and not ("0" <= ch <= "9"):
            try:
                out.append(str(unicodedata.digit(ch)))
                continue
            except (TypeError, ValueError):
                pass
        out.append({"٫": ",", "٬": " ", "٪": "%"}.get(ch, ch))
    return "".join(out)


_NUM = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,'’   ]\d{3})+(?![\d])(?:[.,]\d+)?|\d+(?:[.,]\d+)?)")


def _values(token: str) -> List[float]:
    """Possible values of a written number: "3,5" → 3.5; "1.000" → 1000 or 1.0; "3 500" → 3500."""
    t = token.replace("’", "'")
    m = re.fullmatch(r"(\d+)([.,])(\d+)", t)
    if m:
        dec = float(m.group(1) + "." + m.group(3))
        if len(m.group(3)) == 3:
            return [dec, float(m.group(1) + m.group(3))]
        return [dec]
    m = re.fullmatch(r"(\d{1,3}(?:[.,'   ]\d{3})+)(?:([.,])(\d+))?", t)
    if m:
        whole = re.sub(r"[.,'   ]", "", m.group(1))
        frac = m.group(3)
        return [float(whole + ("." + frac if frac else ""))]
    return [float(t)]


def numbers(text: str) -> List[List[float]]:
    return [_values(m.group(1)) for m in _NUM.finditer(ascii_digits(text))]


def same_numbers(a: str, b: str) -> bool:
    """True when the two texts state the same multiset of numbers (each written number may be read either way
    when ambiguous, e.g. 1.000 / 1,000)."""
    na, nb = numbers(a), numbers(b)
    if len(na) != len(nb):
        return False
    match: Dict[int, int] = {}

    def fits(x: List[float], y: List[float]) -> bool:
        return any(abs(p - q) <= 1e-6 * max(1.0, abs(p)) for p in x for q in y)

    def augment(i: int, seen: set) -> bool:
        for j in range(len(nb)):
            if j not in seen and fits(na[i], nb[j]):
                seen.add(j)
                if j not in match or augment(match[j], seen):
                    match[j] = i
                    return True
        return False
    return all(augment(i, set()) for i in range(len(na)))


# Unit spellings (lower case) → canonical unit. Several scripts; a unit spelling not listed counts as missing,
# so an unknown spelling makes the gate fail closed (the checked local text is shown).
UNIT_ALIASES = {
    "mm": ["mm", "мм", "ملم", "مم", "χιλ"], "cm": ["cm", "см", "سم"], "km": ["km", "км", "كم"],
    "kg": ["kg", "кг", "كغ", "كجم", "كلغ", "kilogram", "kilograma", "kilogramm", "kilogramme", "kilograms", "kilogramów",
           "килограм", "килограмм", "килограма"],
    "g": ["g", "г", "غ", "gram", "grama", "gramm", "grams"],
    "t": ["t", "т", "طن", "tona", "tone", "tonne", "tonnes", "tons", "tonnen", "tonna", "тонна", "тона", "тонн"],
    "l": ["l", "л", "لتر", "litre", "litres", "liter", "litara", "litri", "litre", "литр", "литар", "литара"],
    "ml": ["ml", "мл", "مل"],
    "ha": ["ha", "га", "ха", "هكتار", "hektar", "hektara", "hektare", "hectare", "hectares", "hektár", "hektárov",
           "hectárea", "hectáreas", "ettaro", "ettari", "гектар", "гектара", "хектар", "хектара"],
    "%": ["%", "٪"], "°C": ["°c", "° c", "°с", "° с"],
    # Spec 036 FR-016: local and imperial units, so a value converted by a translation fails closed (units_changed)
    "°F": ["°f", "° f", "℉"],
    "daa": ["daa", "dka", "дка", "dekar", "dekara", "dekár", "декар", "декара", "декари", "στρέμμα", "στρέμματα",
            "στρ.", "στρ", "dönüm", "donum", "dunum", "dynym", "dylym"],
    "ac": ["ac", "acre", "acres"],
    "lb": ["lb", "lbs", "pound", "pounds"],
    "in": ["inch", "inches", "″"],
    "gal": ["gal", "gallon", "gallons"],
}
UNIT_ALIASES["kg"] = UNIT_ALIASES["kg"] + ["κιλά", "κιλό", "κγ"]          # spec 036 (Greek spellings)
UNIT_ALIASES["ha"] = UNIT_ALIASES["ha"] + ["εκτάριο", "εκτάρια", "hektár"]
_ALIAS = {}
for _canon, _spellings in UNIT_ALIASES.items():
    for _s in _spellings:
        _ALIAS.setdefault(_s, _canon)
_PER_AREA = ["/ha", "/ га", "/га", "/ха", "/هكتار", "/hektar", "/hectare", "per ha", "per hectare", "pro ha", "pro hektar",
             "je ha", "je hektar", "po ha", "po hektaru", "na ha", "на га", "на гектар", "par ha", "par hectare",
             "à l'hectare", "al ettaro", "por hectárea", "por ha", "hektáronként", "na hektar", "لكل هكتار",
             "/ ha"]
# Spec 036 FR-016: per-decare/stremma and per-acre forms (canonical "/daa" and "/ac"); a dose added in a local area
# unit is a dose (fails closed).
_PER_LOCAL = ["/дка", "/dka", "/da", "/daa", "/dekar", "/декар", "на дка", "na dekar", "dekar başına", "/στρ.", "/στρ",
              "ανά στρέμμα", "/dönüm", "dönüm başına"]
_PER_ACRE = ["/ac", "/acre", "per acre", "an acre", "/a"]
_PER_AREA = _PER_AREA + _PER_LOCAL + _PER_ACRE
_UNIT_RE = re.compile(
    r"(?<![\d.,])(\d+(?:[.,'’   ]\d+)*)\s*(" + "|".join(re.escape(s) for s in sorted(_ALIAS, key=len, reverse=True))
    + r")(?![^\W\d_])(\s*(?:n|N|н|Н)(?![^\W\d_]))?(\s*(?:" + "|".join(re.escape(s) for s in sorted(_PER_AREA, key=len, reverse=True))
    + r")(?![^\W\d_]))?", re.I)
MASS_VOLUME = {"kg", "g", "t", "l", "ml"}


_PER_SUFFIX = {**{p: "/daa" for p in _PER_LOCAL}, **{p: "/ac" for p in _PER_ACRE}}
# "in" (inch) only right after a number and not followed by a word ("0.79 in (20 mm)", but not "2 in der Woche").
_INCH_RE = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*in(?=\s*(?:$|[^\w\s]|\(|\d))", re.I)


def units(text: str) -> List[Tuple[str, str]]:
    """(number as written, canonical unit) pairs, e.g. ("45", "kg/ha"); per-area units end in /ha (spec 036: /daa
    for decare/stremma forms, /ac for per-acre forms)."""
    out = []
    plain = ascii_digits(text)
    for m in _UNIT_RE.finditer(plain):
        unit = _ALIAS.get(m.group(2).lower(), m.group(2).lower())
        if m.group(4):
            unit += _PER_SUFFIX.get(m.group(4).strip().lower(), "/ha")
        out.append((m.group(1), unit))
    for m in _INCH_RE.finditer(plain):
        out.append((m.group(1), "in"))
    return out


def doses(text: str) -> List[Tuple[float, str]]:
    """Number + mass or volume unit + per area (kg/ha, l/ha, t/ha, g/ha, ml/ha) in any listed spelling."""
    out = []
    for num, unit in units(text):
        base, _, per = unit.partition("/")
        if per in ("ha", "daa", "ac") and base in MASS_VOLUME | {"lb", "gal"}:
            out.append((round(_values(num.replace(" ", ""))[0], 6), unit))
    return out


CITATION = re.compile(r"\[\d+\]|\b[a-z0-9]+(?:-[a-z0-9]+){2,}\b")


def citation_markers(text: str) -> List[str]:
    return sorted(CITATION.findall(text or ""))

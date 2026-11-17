
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_ARABIC_LETTER = re.compile(r"[ء-غف-يٮ-ۓۺ-ۿ]")
_LATIN_LETTER = re.compile(r"[A-Za-zÀ-ɏ]")
_WORD = re.compile(r"[^\W_]+")


def normalize(text: str) -> str:
    """Lowercase, without accents, Arabic diacritics or tatweel, with one form for the Arabic
    letters people write in several ways: أ إ آ → ا, ؤ → و, ئ → ي, ة → ه, ى → ي."""
    text = unicodedata.normalize("NFKC", text or "").replace("ـ", "")
    text = "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")  # accents, harakat, hamza above/below
    text = unicodedata.normalize("NFC", text)
    text = text.replace("ٱ", "ا").replace("ة", "ه").replace("ى", "ي")
    return text.replace("’", "'").replace("ʼ", "'").casefold()


def words(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


# --------------------------------------------------------------------------- the avoid list
_FRENCH_ARTICLES = {"le", "la", "les", "l", "un", "une", "des", "du", "de", "d"}
_ARABIC_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال")
_ARABIC_SUFFIXES = ("ات", "ون", "ين", "ها", "ه")
_FRENCH_ENDINGS = (("euses", "eur"), ("euse", "eur"), ("trices", "teur"), ("trice", "teur"),
                   ("eres", "er"), ("ere", "er"), ("ennes", "en"), ("enne", "en"),
                   ("eaux", "eau"), ("aux", "al"))


def _stem(token: str) -> str:
    """A light stem, the same on both sides of a comparison: article prefixes and plural or
    feminine endings go, so « الإشارة » meets « اشارة » and « visiteuse » meets « visiteur »."""
    if _ARABIC_LETTER.search(token):
        for prefix in _ARABIC_PREFIXES:
            if token.startswith(prefix) and len(token) - len(prefix) >= 2:
                token = token[len(prefix):]
                break
        else:
            if token.startswith("و") and len(token) >= 4:
                token = token[1:]
        for suffix in _ARABIC_SUFFIXES:
            if token.endswith(suffix) and len(token) - len(suffix) >= 2:
                return token[:-len(suffix)]
        return token
    for ending, replacement in _FRENCH_ENDINGS:
        if token.endswith(ending) and len(token) > len(ending) + 1:
            return token[:-len(ending)] + replacement
    if len(token) > 3 and token[-1] in "sx":
        token = token[:-1]
    if len(token) >= 6 and token.endswith("e"):
        token = token[:-1]
    return token


def _stems(text: str) -> list[str]:
    return [_stem(t) for t in words(text) if t not in _FRENCH_ARTICLES]


def mentions(text: str, phrase: str) -> bool:
    """Whether text names the phrase, whatever its article, number, gender, accents or Arabic
    spelling. A synonym is not caught: the director lists it."""
    wanted = _stems(phrase)
    if not wanted:
        return False
    found = _stems(text)
    if any(found[i:i + len(wanted)] == wanted for i in range(len(found) - len(wanted) + 1)):
        return True
    # Arabic glues prepositions and pronouns to words: also look for the letters themselves.
    phrase_norm = normalize(phrase).strip()
    return bool(_ARABIC_LETTER.search(phrase_norm)) and phrase_norm in normalize(text)


# --------------------------------------------------------------------------- refusals
_REFUSALS = [re.compile(r"(?<!\w)" + re.escape(normalize(p)) + r"(?!\w)") for p in (
    "je ne peux pas", "je ne suis pas en mesure", "je suis désolé", "je suis désolée",
    "désolé,", "désolée,", "en tant qu'ia", "en tant que modèle", "impossible de décrire",
    "i can't", "i cannot", "i'm sorry", "i am sorry", "i'm unable", "i am unable", "as an ai",
    "لا أستطيع", "لا يمكنني", "عذرا", "آسف", "أعتذر",
    "ما نجمش", "ما نقدرش", "سامحني")]


def looks_like_refusal(text: str) -> bool:
    """The model said it would not or could not describe: never a description to speak."""
    lowered = normalize(text)
    return any(pattern.search(lowered) for pattern in _REFUSALS)


# --------------------------------------------------------------------------- script, language
_ENGLISH = {"the", "and", "with", "his", "her", "is", "are", "of", "to", "into", "from",
            "while", "puts", "looks", "takes", "walks", "holds", "opens"}
_FRENCH = {"le", "la", "les", "et", "avec", "sur", "dans", "du", "des", "une", "un", "il",
           "elle", "sa", "son", "ses", "est", "vers", "au", "aux", "de", "puis"}


def script_problem(text: str, langue: str) -> str:
    """Why the text is not in the track's language, or '' when it looks right."""
    arabic, latin = len(_ARABIC_LETTER.findall(text)), len(_LATIN_LETTER.findall(text))
    if arabic + latin < 4:
        return ""
    share = arabic / (arabic + latin)
    if langue in ("ar", "aeb") and share < 0.5:
        return "Écriture inattendue : cette piste s'écrit en caractères arabes."
    if langue == "fr":
        if share > 0.5:
            return "Écriture inattendue : cette piste est en français."
        tokens = words(text)
        english = sum(t in _ENGLISH for t in tokens)
        if english >= 2 and english > sum(t in _FRENCH for t in tokens):
            return "Ce texte semble en anglais : cette piste est en français."
    return ""


# Words that only Standard Arabic uses in a description, and words only Derja uses.
_STANDARD = {normalize(w) for w in (
    "إلى", "التي", "الذي", "هذا", "هذه", "ذلك", "تلك", "سوف", "لكن", "بينما", "حيث", "نحو",
    "أمام", "ينظر", "تنظر", "يضع", "تضع", "يجلس", "تجلس", "يقف", "تقف", "ينهض", "تنهض",
    "يمسك", "تمسك")}
_DERJA = {normalize(w) for w in (
    "باش", "بش", "برشا", "توا", "شنوة", "كيفاش", "ياسر", "فما", "متاع", "تحط", "يحط", "تخزر",
    "يخزر", "هاذا", "هاذي", "هوما", "زادة", "ماش", "يشد", "تشد", "قدام", "برك", "ديما",
    "يغزر", "تغزر")}


def _hit(word: str, vocabulary: set[str]) -> bool:
    return word in vocabulary or (word.startswith("و") and word[1:] in vocabulary)


def looks_like_standard_arabic(text: str) -> bool:
    """A Derja track that reads like Standard Arabic: two Standard words or more, no Derja."""
    tokens = words(text)
    return (sum(_hit(t, _STANDARD) for t in tokens) >= 2
            and not any(_hit(t, _DERJA) for t in tokens))


def dialogue_language(text: str) -> str | None:
    """The track language that matches the film's dialogue: « fr » in Latin letters, « aeb » in
    Arabic letters unless it reads more like Standard Arabic (« ar »). None: too little to tell."""
    arabic, latin = len(_ARABIC_LETTER.findall(text or "")), len(_LATIN_LETTER.findall(text or ""))
    if arabic + latin < 20:
        return None
    if latin > arabic:
        return "fr"
    tokens = words(text)
    standard = sum(_hit(t, _STANDARD) for t in tokens)
    return "ar" if standard > sum(_hit(t, _DERJA) for t in tokens) else "aeb"


def too_similar(text: str, previous: str, threshold: float = 0.8) -> bool:
    """Nearly the same words as the passage before."""
    a, b = normalize(text).strip(), normalize(previous).strip()
    return bool(a and b) and SequenceMatcher(None, a, b).ratio() >= threshold

"""Faces, gestures and body language: what the track may say about emotions.

The vision-language model reads what the actors show; these plain rules (no model call) check
how the text names it. What is seen comes first (« elle baisse les yeux et serre ses mains »).
A probable emotion may follow, only next to the visible signs that support it and with a
nuance (« l'air inquiet »). Certainty and psychological or medical labels are refused on the
AI's text and flagged on a person's. The director can rule out emotion words altogether with
the « signes » mode, which keeps Wasf's earlier, strict behaviour.

The word lists are a first version; the Arabic and Derja ones in particular are for native
speakers to complete. A missing word lets a passage through without a flag: it never blocks one.
"""
from __future__ import annotations

import re

from .textnorm import _stems, mentions

MODES = {
    "nuancees": "l'IA peut nommer une émotion probable, appuyée sur des signes visibles et nuancée",
    "signes": "l'IA décrit seulement les signes visibles, sans mot d'émotion",
}
DEFAULT_MODE = "nuancees"
UNSURE = 0.5   # below this certainty, an emotion the model names is a guess

# Masculine and feminine forms are both listed: the light stemming does not join them.
EMOTIONS = {
    "fr": ["triste", "tristesse", "heureux", "heureuse", "bonheur", "joie", "joyeux", "joyeuse",
           "content", "contente", "ravi", "ravie", "en colère", "colère", "furieux", "furieuse",
           "fureur", "énervé", "énervée", "irrité", "irritée", "agacé", "agacée", "peur",
           "effrayé", "effrayée", "terrifié", "terrifiée", "apeuré", "apeurée", "paniqué",
           "paniquée", "panique", "inquiet", "inquiète", "inquiétude", "anxieux", "anxieuse",
           "angoissé", "angoissée", "angoisse", "nerveux", "nerveuse", "nervosité", "stressé",
           "stressée", "surpris", "surprise", "étonné", "étonnée", "stupéfait", "stupéfaite",
           "choqué", "choquée", "confus", "confuse", "perplexe", "déconcerté", "déconcertée",
           "frustré", "frustrée", "frustration", "déçu", "déçue", "déception", "ému", "émue",
           "émotion", "gêné", "gênée", "embarrassé", "embarrassée", "mal à l'aise", "honteux",
           "honteuse", "honte", "soulagé", "soulagée", "soulagement", "fier", "fière", "fierté",
           "amoureux", "amoureuse", "tendresse", "affectueux", "affectueuse", "attendri",
           "attendrie", "jaloux", "jalouse", "jalousie", "méfiant", "méfiante", "dégoûté",
           "dégoûtée", "dégoût", "désespéré", "désespérée", "désespoir", "dévasté", "dévastée",
           "bouleversé", "bouleversée", "abattu", "abattue", "mélancolique", "nostalgique",
           "euphorique", "serein", "sereine", "émerveillé", "émerveillée", "résigné", "résignée"],
    "ar": ["حزين", "حزينة", "حزن", "سعيد", "سعيدة", "فرح", "فرحة", "غاضب", "غاضبة", "غضب",
           "خائف", "خائفة", "خوف", "قلق", "قلقة", "متوتر", "متوترة", "مندهش", "مندهشة", "دهشة",
           "مرتبك", "مرتبكة", "محبط", "محبطة", "مصدوم", "مصدومة", "منزعج", "منزعجة", "محرج",
           "محرجة", "يائس", "يائسة", "مسرور", "مسرورة", "مرتاح", "مرتاحة", "حنان"],
    "aeb": ["فرحان", "فرحانة", "حزين", "حزينة", "متغشش", "متغششة", "مقلق", "مقلقة", "خايف",
            "خايفة", "مستغرب", "مستغربة", "محشوم", "محشومة", "مقهور", "مقهورة", "متوتر",
            "متوترة", "مصدوم", "مصدومة", "مكرز", "مكرزة", "منرفز", "منرفزة"],
}

# What can be seen: parts of the face and body, expressions, gestures, postures.
SIGNS = {
    "fr": ["yeux", "œil", "regard", "regarde", "regardent", "fixe", "fixent", "cligne",
           "paupières", "sourcil", "sourcils", "fronce", "froncent", "froncé", "froncés",
           "plisse", "écarquille", "front", "larme", "larmes", "pleure", "pleurent",
           "pleurs", "sanglote", "sanglots", "sourit", "sourient", "sourire", "souriant",
           "souriante", "rit", "rient", "rire", "riant", "grimace", "bouche", "lèvre", "lèvres",
           "mâchoire", "joue", "joues", "visage", "menton", "tête", "hoche", "secoue", "baisse",
           "baissent", "lève", "lèvent", "relève", "détourne", "évite", "main", "mains", "doigt",
           "doigts", "poing", "poings", "serre", "serrent", "crispe", "crispé", "crispée",
           "tremble", "tremblent", "tremblante", "frissonne", "bras", "croise", "croisent",
           "croisés", "épaule", "épaules", "hausse", "dos", "voûté", "voûtée", "recule",
           "reculent", "avance", "penche", "penché", "penchée", "approche", "éloigne",
           "recroquevillé", "recroquevillée", "immobile", "figé", "figée", "agite", "gesticule",
           "montre", "pointe", "désigne", "salue", "signe", "embrasse", "enlace", "étreint",
           "caresse", "frappe", "repousse", "pousse", "attrape", "saisit", "couvre",
           "essuie", "mord", "rougit", "pâlit", "transpire", "sueur", "soupire", "genou",
           "genoux", "jambes", "pieds", "piétine", "tape", "fuyant", "sursaute", "hésite",
           "titube", "effondre"],
    "ar": ["عينيه", "عينيها", "عيناه", "عيناها", "دموع", "دمعة", "يبكي", "تبكي", "يبتسم",
           "تبتسم", "ابتسامة", "يضحك", "تضحك", "حاجبيه", "حاجبيها", "يعبس", "تعبس", "قبضته",
           "قبضتها", "قبضتيه", "يقبض", "تقبض", "يديه", "يديها", "ذراعيه", "ذراعيها", "كتفيه",
           "كتفيها", "رأسه", "رأسها", "وجهه", "وجهها", "شفتيه", "شفتيها", "يرتجف", "ترتجف",
           "يشير", "تشير", "يلوح", "تلوح", "يعانق", "تعانق", "يصافح", "تصافح", "ينظر", "تنظر",
           "يحدق", "تحدق", "يتراجع", "تتراجع", "ينحني", "تنحني", "يقترب", "تقترب", "يبتعد",
           "تبتعد", "يهز", "تهز", "يخفض", "تخفض", "يرفع", "ترفع", "يغطي", "تغطي", "يمسح",
           "تمسح", "نظرته", "نظرتها"],
    "aeb": ["عينيه", "عينيها", "دموع", "يبكي", "تبكي", "يضحك", "تضحك", "يتبسم", "تتبسم",
            "يديه", "يديها", "كتافو", "كتافها", "راسو", "راسها", "وجهو", "وجهها", "يخزر",
            "تخزر", "يشاور", "تشاور", "يهز", "تهز", "يرعش", "ترعش", "يقرب", "تقرب", "يبعد",
            "تبعد", "يعنق", "تعنق", "يسلم", "تسلم"],
}

# A nuance: the emotion is offered as an impression, not stated as a fact.
HEDGES = {
    "fr": ["semble", "semblent", "sembler", "l'air", "paraît", "parait", "paraissent",
           "on dirait", "comme si", "visiblement", "peut-être", "sans doute", "probablement",
           "un peu", "presque"],
    "ar": ["يبدو", "تبدو", "يبدوان", "يبدون", "كأن", "كأنه", "كأنها", "ربما", "على ما يبدو",
           "قليلا", "يظهر لي", "ظهر لي"],
    # « ظهر لي » in two words: « ظهر » alone is also the back (« يدير ظهرو »).
    "aeb": ["يبان", "تبان", "يظهر", "تظهر", "كأنو", "كأنها", "باين", "باينة", "ربما", "شوية",
            "يظهر لي", "ظهر لي", "ظهرلي"],
}

# Certainty about what someone feels: never allowed.
CERTAINTY = {
    "fr": ["clairement", "évidemment", "manifestement", "forcément", "assurément",
           "sans aucun doute", "de toute évidence", "à coup sûr", "définitivement",
           "indéniablement", "incontestablement"],
    "ar": ["بالتأكيد", "بكل تأكيد", "حتما", "بلا شك", "دون شك", "من الواضح", "قطعا", "بوضوح"],
    "aeb": ["أكيد", "بالحق", "من غير شك", "واضح", "بالطبيعة", "sûr", "sûre"],
}

# Right before a certainty word, a negation turns it into a nuance: « موش sûr », « موش أكيد »,
# « pas forcément ». A comma ends it: « il fait un pas, clairement furieux » stays certain.
NEGATIONS = {"fr": ["pas", "guère"], "ar": ["ليس", "ليست", "غير"],
             "aeb": ["مش", "موش", "ماهوش", "ماهيش"]}

# Psychological or medical labels: a film describes what it shows, it does not diagnose.
DIAGNOSES = {
    "fr": ["déprimé", "déprimée", "dépressif", "dépressive", "dépression", "bipolaire",
           "schizophrène", "psychotique", "paranoïaque", "hystérique", "névrosé", "névrosée",
           "traumatisé", "traumatisée", "psychopathe", "sociopathe", "suicidaire", "anorexique",
           "maniaque", "malade mental", "malade mentale", "autiste", "trouble anxieux",
           "aliéné", "aliénée"],
    "ar": ["مكتئب", "مكتئبة", "اكتئاب", "هستيري", "هستيرية", "مريض نفسي", "مريضة نفسية"],
    "aeb": ["مكتئب", "مكتئبة", "مهبول", "مهبولة", "مريض نفسي", "مريضة نفسية"],
}

# Added from the team's Derja notes (13/11/2026), not yet checked by a native speaker:
# docs/DERJA_A_RELIRE.md lists them for review. A wrong word here only adds or misses a flag.
# Possessives come in both spellings (« راسو », « راسه »), verbs in both genders.
DERJA_A_RELIRE = {
    "émotions": ["مبسوط", "مبسوطة", "متقلق", "متقلقة", "معصب", "معصبة", "متفاجئ", "متفاجئة",
                 "محرج", "محرجة", "متحشم", "متحشمة", "مرتاح", "مرتاحة", "متردد", "مترددة",
                 "مخنوق", "مخنوقة", "متأثر", "متأثرة"],
    "signes": ["يبتسم", "تبتسم", "يدمعو", "يدمعوا", "تدمع", "حواجبو", "حواجبه", "حواجبها",
               "يقطب", "تقطب", "يغمض", "تغمض", "يهبط", "تهبط", "يعض", "تعض", "شفايفو", "شفايفه",
               "شفايفها", "يتجنب", "تتجنب", "يشبك", "تشبك", "يعقد", "تعقد", "يكتف", "تكتف",
               "مكتف", "قبضتو", "قبضتها", "صبعو", "صبعه", "صبعها", "يحرك", "تحرك", "يغطي",
               "تغطي", "يلتفت", "تلتفت", "ينكس", "تنكس", "يتراجع", "تتراجع", "راسه", "وجهه",
               "كتافه", "يغزر", "تغزر"],
    # Whole phrases where one word would mislead: « ما ينجمش يحكي » is « he can't speak »,
    # not a nuance, so « ينجم » alone is not listed.
    "nuances": ["يمكن", "على ما يبدو", "على ما يظهر", "موش واضح", "صعيب نعرفو", "ينجم يكون",
                "تنجم تكون", "موش بالضرورة", "ما ننجموش نجزمو"],
    "certitude": ["بالتأكيد", "مية بالمية", "بلا شك", "مستحيل يكون"],
    "diagnostics": ["مجنون", "مجنونة", "ديبريسيون", "دبريسيون"],
}
EMOTIONS["aeb"] += DERJA_A_RELIRE["émotions"]
SIGNS["aeb"] += DERJA_A_RELIRE["signes"]
HEDGES["aeb"] += DERJA_A_RELIRE["nuances"]
CERTAINTY["aeb"] += DERJA_A_RELIRE["certitude"]
DIAGNOSES["aeb"] += DERJA_A_RELIRE["diagnostics"]

# Judgements of taste, flagged in both modes, as before.
JUDGEMENTS = {"fr": ["magnifique", "beau", "belle"], "ar": ["جميل", "جميلة"],
              "aeb": ["مزيان", "مزيانة"]}

# Wasf's earlier list, kept word for word for the « signes » mode.
STRICT_HINTS = {
    "fr": ["semble", "semblent", "on dirait", "visiblement", "magnifique", "beau", "belle",
           "triste", "heureux", "heureuse", "en colère", "effrayé", "effrayée"],
    "ar": ["يبدو", "تبدو", "جميل", "جميلة", "حزين", "حزينة", "سعيد", "سعيدة", "غاضب", "غاضبة"],
    "aeb": ["يظهر", "تظهر", "مزيان", "مزيانة", "فرحان", "فرحانة", "حزين", "حزينة", "متغشش"],
}

_SENTENCE = re.compile(r"[.!?؟;؛…]+")


def _unique(items) -> list[str]:
    return list(dict.fromkeys(items))


def _found(text: str, terms) -> list[str]:
    return [term for term in _unique(terms) if term and mentions(text, term)]


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(text or "") if s.strip()]


_CLAUSE = re.compile(r"[,،]+")


def _denied(sentence: str, term: str, langue: str) -> bool:
    """Whether every use of the word in the sentence comes right after a negation."""
    negations = {s for n in NEGATIONS.get(langue, []) for s in _stems(n)}
    wanted = _stems(term)
    uses = denied = 0
    for clause in _CLAUSE.split(sentence):
        tokens = _stems(clause)
        for i in range(len(tokens) - len(wanted) + 1):
            if wanted and tokens[i:i + len(wanted)] == wanted:
                uses += 1
                denied += i > 0 and tokens[i - 1] in negations
    return uses > 0 and denied == uses


def _without_names(text: str, names) -> str:
    """Character names out of the way: « Saïd » or « Farah » is a name, not an emotion."""
    for name in sorted({str(n).strip() for n in names or [] if str(n).strip()}, key=len,
                       reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " ", text, flags=re.IGNORECASE)
    return text


def _strict_hits(text: str, langue: str) -> list[str]:
    lowered = text.lower()
    return [h for h in STRICT_HINTS.get(langue, [])
            if re.search(rf"(?<!\w){re.escape(h)}(?!\w)", lowered)]


def named_emotions(text: str, langue: str, names=None) -> list[str]:
    """The emotion words a text uses (character names left aside)."""
    return _found(_without_names(text or "", names), EMOTIONS.get(langue, []))


def _certainty(emotion: dict):
    value = emotion.get("certitude") if isinstance(emotion, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def check_emotions(text: str, *, langue: str, mode: str = DEFAULT_MODE, dialogue: str = "",
                   previous: str = "", emotions: list[dict] | None = None, strict: bool = True,
                   names=None) -> list[dict]:
    """How the text handles what characters show and feel. Same format as agent.run_checks.

    emotions: what the model said it supposed, with its certainty (prompts.parse_reply).
    strict: True for the AI's own text, where certainty and labels block the passage and the
    agent rewrites it; False for a person's edit, where they are only flagged.
    names: character names, never read as emotion words."""
    text = _without_names(text or "", names)
    if not text.strip():
        return []
    level = "erreur" if strict else "attention"
    feelings, signs = EMOTIONS.get(langue, []), SIGNS.get(langue, [])
    results: list[dict] = []

    labels = _found(text, DIAGNOSES.get(langue, []))
    if labels:
        results.append({"niveau": level, "code": "diagnostic",
                        "message": "Étiquette psychologique ou médicale (" + ", ".join(labels)
                                   + ") : décrivez ce que l'on voit, sans diagnostic."})
    sure, bare, flat = [], [], []
    for sentence in _sentences(text):
        named = _found(sentence, feelings)
        if not named:
            continue
        sure += [w for w in _found(sentence, CERTAINTY.get(langue, []))
                 if not _denied(sentence, w, langue)]
        if not _found(sentence, signs):
            bare += named
        if not _found(sentence, HEDGES.get(langue, [])):
            flat += named
    if sure:
        results.append({"niveau": level, "code": "certitude",
                        "message": "Affirme une émotion avec certitude (" + ", ".join(_unique(sure))
                                   + ") : décrivez le signe visible et nuancez l'émotion."})

    if mode == "signes":
        hints = _unique(_strict_hits(text, langue) + _found(text, feelings))
        if hints:
            results.append({"niveau": "attention", "code": "interpretation",
                            "message": "Interprétation possible, à vérifier : " + ", ".join(hints)
                                       + "."})
    else:
        if bare:
            results.append({"niveau": "attention", "code": "interpretation",
                            "message": "Émotion nommée sans signe visible ("
                                       + ", ".join(_unique(bare)) + ") : ajoutez ce que l'on voit "
                                       "(« elle baisse les yeux ») ou retirez l'émotion."})
        judged = _found(text, JUDGEMENTS.get(langue, []))
        if judged:
            results.append({"niveau": "attention", "code": "interpretation",
                            "message": "Jugement possible, à vérifier : " + ", ".join(judged) + "."})
        unsure = [c for c in (_certainty(e) for e in emotions or []) if c is not None and c < UNSURE]
        if flat and unsure:
            results.append({"niveau": "attention", "code": "emotion_incertaine",
                            "message": "L'IA n'est pas sûre de l'émotion qu'elle nomme (certitude "
                                       f"{round(min(unsure) * 100)} %) : nuancez-la ou gardez "
                                       "seulement les signes."})

    said = [w for w in _found(text, feelings) if dialogue and mentions(dialogue, w)]
    if said:
        results.append({"niveau": "attention", "code": "emotion_dialogue",
                        "message": "Le dialogue dit déjà cette émotion (" + ", ".join(said)
                                   + ") : inutile de la décrire."})
    if previous:
        now = set(_found(text, signs))
        shared = now & set(_found(_without_names(previous, names), signs))
        if len(shared) >= 2 and len(shared) >= 0.6 * len(now):
            results.append({"niveau": "attention", "code": "geste_repete",
                            "message": "Redécrit des gestes ou des expressions du passage précédent ("
                                       + ", ".join(sorted(shared)) + ") : gardez-les seulement "
                                       "s'ils ont changé."})
    return results


# --------------------------------------------------------------------------- evidence checks
# These compare what the model said it saw with what it wrote and what it supposed. They rest
# on its own structured reply, not on the word lists alone, so they also work where a list is
# missing a word. They apply to the AI's text: a person who edits has looked at the image.

# One gesture, several ways to say it: a description may paraphrase what the model observed.
SAME_GESTURE = {
    "fr": [{"montre", "pointe", "désigne", "indique", "doigt", "tend"},
           {"sourit", "sourient", "sourire", "souriant", "souriante", "rit", "rient", "rire", "riant"},
           {"regarde", "regardent", "regard", "fixe", "fixent", "observe", "contemple", "yeux"},
           {"recule", "reculent", "éloigne", "écarte"},
           {"approche", "rapproche", "avance"},
           {"hoche", "acquiesce"},
           {"pleure", "pleurent", "pleurs", "larme", "larmes", "sanglote", "sanglots"},
           {"serre", "serrent", "crispe", "crispé", "crispée", "poing", "poings"},
           {"salue", "signe", "agite", "main", "mains"},
           {"croise", "croisent", "croisés", "bras"},
           {"baisse", "baissent", "incline", "penche", "penché", "penchée"},
           {"tremble", "tremblent", "tremblante", "frissonne"},
           {"fronce", "froncent", "froncé", "froncés", "sourcil", "sourcils"},
           {"détourne", "évite", "fuyant"}],
    "ar": [{"يشير", "تشير", "إصبعه", "إصبعها"}, {"يبتسم", "تبتسم", "ابتسامة", "يضحك", "تضحك"},
           {"ينظر", "تنظر", "يحدق", "تحدق", "نظرته", "نظرتها"}, {"يبكي", "تبكي", "دموع", "دمعة"},
           {"يتراجع", "تتراجع", "يبتعد", "تبتعد"}, {"يقترب", "تقترب"}],
    "aeb": [{"يشاور", "تشاور", "صبعو", "صبعه", "صبعها"},
            {"يضحك", "تضحك", "يتبسم", "تتبسم", "يبتسم", "تبتسم"},
            {"يخزر", "تخزر", "يغزر", "تغزر"},
            {"يبكي", "تبكي", "دموع", "يدمعو", "يدمعوا", "تدمع"},
            {"يبعد", "تبعد", "يتراجع", "تتراجع"}, {"يقرب", "تقرب"},
            # From the team's Derja notes, to be checked like DERJA_A_RELIRE:
            {"يهبط", "تهبط", "ينكس", "تنكس"},
            {"يقطب", "تقطب", "حواجبو", "حواجبه", "حواجبها"},
            {"يكتف", "تكتف", "مكتف", "يعقد", "تعقد", "يشبك", "تشبك"}],
}

AMBIGUOUS = 0.6     # competing readings, none at least this sure: the scene is ambiguous
CROWDED = 6         # distinct gestures and expressions in one passage: probably too many


def _content(text: str) -> set[str]:
    return {s for s in _stems(text) if len(s) > 2}


def _supported(clue: str, observations: list[str]) -> bool:
    wanted = _content(clue)
    return not wanted or any(wanted & _content(o) for o in observations)


def _key(name: str) -> str:
    return " ".join(_stems(name or ""))


def _ways_to_say(sign: str, langue: str) -> set[str]:
    stem = _key(sign)
    ways = {sign}
    for group in SAME_GESTURE.get(langue, []):
        if stem in {_key(word) for word in group}:
            ways |= group
    return ways


def describes_people(text: str, langue: str, names=None) -> bool:
    """Does the text say anything about gestures, faces or feelings?"""
    bare = _without_names(text or "", names)
    return bool(_found(bare, SIGNS.get(langue, [])) or named_emotions(text, langue, names))


def check_evidence(text: str, *, langue: str, observations: list[str] | None = None,
                   emotions: list[dict] | None = None, structured: bool = True,
                   names=None, unconfirmed: list[str] | None = None,
                   supports: list[list[int]] | None = None) -> list[dict]:
    """Is what the text says about faces and gestures backed by what the model reported?

    unconfirmed: visual claims rejected on a second look at the images.
    supports: per sentence, the numbers of the observations it rests on, as the model gave
    them. These two checks use no word list, so they work in every language."""
    text = text or ""
    if not text.strip():
        return []
    observations = [o for o in observations or [] if o]
    emotions = [e for e in emotions or [] if isinstance(e, dict) and e.get("emotion")]
    bare = _without_names(text, names)
    # One entry per stem: « sourcil » and « sourcils » are one sign.
    signs = list({_key(s): s for s in _found(bare, SIGNS.get(langue, []))}.values())
    hedged = bool(_found(bare, HEDGES.get(langue, [])))
    results: list[dict] = []

    def named(label: str) -> bool:
        return mentions(text, label)

    by_person: dict[str, list[dict]] = {}
    for e in emotions:
        by_person.setdefault(_key(e.get("qui", "")), []).append(e)
    for readings in by_person.values():
        labels = _unique(e["emotion"] for e in readings)
        sure = [c for c in (_certainty(e) for e in readings) if c is not None]
        settled = any(named(label) for label in labels) or (
            bool(named_emotions(text, langue, names)) and not hedged)
        if len(labels) >= 2 and (not sure or max(sure) < AMBIGUOUS) and settled:
            results.append({"niveau": "attention", "code": "emotion_ambigue",
                            "message": "Plusieurs lectures possibles (" + ", ".join(labels)
                                       + ") : décrivez les signes sans trancher."})
            break

    unsupported = [e["emotion"] for e in emotions if named(e["emotion"]) and not e.get("indices")]
    if unsupported:
        results.append({"niveau": "attention", "code": "sans_preuve",
                        "message": "L'IA nomme « " + ", ".join(_unique(unsupported))
                                   + " » sans dire sur quels signes : vérifiez sur l'image."})
    if observations:
        cited = [c for e in emotions for c in e.get("indices") or []
                 if not _supported(c, observations)]
        if cited:
            results.append({"niveau": "attention", "code": "indice_non_observe",
                            "message": "Signe invoqué mais absent des observations (« "
                                       + cited[0] + " ») : vérifiez sur l'image."})
        # Paraphrase is normal (« tend le bras » for « montre du doigt »): flag only a text whose
        # gestures share nothing at all with what the model said it observed.
        if len(signs) >= 2 and not any(_supported(way, observations)
                                       for sign in signs for way in _ways_to_say(sign, langue)):
            results.append({"niveau": "attention", "code": "signe_non_observe",
                            "message": "Aucun des gestes décrits n'est dans les observations de "
                                       "l'IA (" + ", ".join(signs[:4]) + ") : inventés ? "
                                       "Vérifiez sur l'image."})
    elif structured and (signs or named_emotions(text, langue, names)):
        results.append({"niveau": "attention", "code": "reponse_incomplete",
                        "message": "Le texte décrit gestes ou émotions, mais le modèle n'a rien "
                                   "dit de ce qu'il a vu : relisez avec les images."})
    valid = [[k for k in entry if 1 <= k <= len(observations)] for entry in supports or []]
    if valid and any(not entry for entry in valid):
        results.append({"niveau": "attention", "code": "phrase_sans_appui",
                        "message": "Selon l'IA elle-même, une phrase ne repose sur aucune de ses "
                                   "observations : vérifiez-la sur l'image."})
    rejected = {k for k, o in enumerate(observations, 1) if o in (unconfirmed or [])}
    resting = [entry for entry in valid if entry and set(entry) <= rejected]
    if resting:      # a sentence whose every support was rejected, whatever the wording
        results.append({"niveau": "attention", "code": "signe_non_confirme",
                        "message": "Seconde lecture : une phrase repose sur « "
                                   + observations[resting[0][0] - 1] + " », qui n'a pas été vu "
                                   "sur les images. Vérifiez avant de valider."})
    else:            # no supports given: fall back on the words the text still shares
        still_said = [c for c in unconfirmed or []
                      if _content(_without_names(c, names)) & _content(bare)]
        if still_said:
            results.append({"niveau": "attention", "code": "signe_non_confirme",
                            "message": "Seconde lecture : « " + still_said[0] + " » n'a pas été "
                                       "vu sur les images. Vérifiez avant de valider."})
    if len(signs) >= CROWDED:
        results.append({"niveau": "attention", "code": "surcharge",
                        "message": "Beaucoup de gestes pour un passage : gardez ceux qui comptent "
                                   "pour l'histoire."})
    return results

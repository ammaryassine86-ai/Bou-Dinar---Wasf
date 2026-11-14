"""Prompts given to the vision-language model, and parsing of its replies."""
from __future__ import annotations

import json
import math
import re

from .timecode import fmt_short

LANG_SPECS = {
    "fr": {"nom": "français",
           "consigne": "Écris en français, au présent, en phrases courtes et simples."},
    "ar": {"nom": "arabe standard moderne",
           "consigne": "اكتب بالعربية الفصحى المبسطة، بصيغة المضارع، وبجمل قصيرة وواضحة."},
    # Tunisian films speak Derja with everyday French words in it: the track should sound the same.
    # Models drift to Standard Arabic when they describe, and copy notes written in it: concrete
    # swaps and one sentence in the right tone hold the register better than a general rule.
    "aeb": {"nom": "derja tunisienne telle qu'on la parle, en caractères arabes",
            "consigne": ("Écris en derja tunisienne telle qu'on la parle au quotidien, en caractères "
                         "arabes, avec des phrases courtes. Jamais d'arabe standard : « ton neutre » "
                         "veut dire sans commentaire, pas un registre soutenu. Les notes de la "
                         "réalisation peuvent être en arabe standard ou en français : reprends leur "
                         "sens, jamais leurs mots. Écris aussi tes observations en derja. Garde les "
                         "mots français que les Tunisiens emploient tous les jours, écrits comme en "
                         "derja (« البورتابل », « أورانج »). Par exemple : بالشوية (pas ببطء), "
                         "بشوية بشوية (pas تدريجيا), يغزر (pas ينظر), يقعد (pas يجلس), يوقف (pas "
                         "يقف), يحط (pas يضع), يشد (pas يمسك), يمشي لـ (pas يذهب إلى), اللي (pas "
                         "الذي / التي), هاذا / هاذي (pas هذا / هذه), مبعد (pas ثم), توا (pas الآن), "
                         "برشا (pas كثيرا). Le ton juste : « تقعد حذا الشباك وتغزر للبحر. »")},
}

SYSTEM_PROMPT = """Tu es l'audiodescripteur·rice d'un film, pour des spectateurs aveugles ou malvoyants. Tu écris toute la piste, passage par passage ; la réalisation la relira et l'approuvera : tu ne publies rien toi-même.

Règles :
1. Décris ce qui est visible et utile : actions, personnages, lieux, textes à l'écran, ce que les personnages expriment sans parler. L'essentiel d'abord (qui, fait quoi, où).
2. Présent, troisième personne, ton neutre, phrases naturelles, jamais une liste.
3. Visages et corps : expressions, gestes, posture, hésitations ; entre personnages, qui évite le regard de qui, qui réagit à quoi, qui s'approche ou s'éloigne. Priorité aux changements d'émotion et aux gestes qui comptent pour l'histoire, pas aux mouvements sans importance.
4. Les images sont dans l'ordre, avec leur instant, certaines juste avant la pause : décris ce qui change de l'une à l'autre, pas chaque image, et ne redis pas un état déjà connu qui n'a pas changé.
5. Le signe visible d'abord (« elle baisse les yeux »). Émotions : suis la consigne donnée avec le passage ; jamais de certitude ni de diagnostic (« déprimée ») ; image ambiguë ou signes contradictoires : décris les signes sans conclure et donne toutes les lectures possibles dans « emotions ».
6. Ne répète pas les dialogues ni une émotion qu'ils disent déjà ; n'anticipe pas la suite.
7. Nomme un personnage seulement si sa description permet de le reconnaître, sinon décris-le sans nom (« un homme en chemise bleue ») ; jamais un acteur ni une personne réelle d'après son visage.
8. Respecte l'intention de la réalisation : mets en avant ce qu'elle veut faire remarquer, ne mentionne jamais les éléments à éviter.
9. Respecte strictement le nombre maximal de mots ; rien d'important : description vide.
10. Confiance sous 0,5 si l'image est ambiguë ou si l'essentiel ne tient pas.
11. Réponds uniquement en JSON : {"observations": ["..."], "changements": [{"qui": "...", "avant": "...", "apres": "...", "images": [1, 3]}], "interactions": [{"qui": "...", "envers": "...", "geste": "..."}], "emotions": [{"qui": "...", "emotion": "...", "indices": ["..."], "certitude": 0.0 à 1.0}], "description": "...", "appuis": [[1, 2]], "confiance": 0.0 à 1.0, "remarque": "..."}. Observations : quatre faits visibles au plus, sans émotion ; appuis : pour chaque phrase de la description, les numéros des observations qui la fondent ; une entrée d'« emotions » par lecture possible. Seule la description est lue."""

# How emotions may be named, as the director chose in the intent file (emotions.py).
EMOTION_RULES = {
    "nuancees": ("Émotions : tu peux nommer une émotion probable seulement si plusieurs signes "
                 "visibles l'appuient, avec une nuance (« l'air inquiet », « semble furieux ») et "
                 "ces signes dans la même phrase."),
    "signes": ("Émotions : la réalisation ne veut aucun mot d'émotion. Décris seulement les "
               "signes visibles (« elle baisse les yeux » plutôt que « elle est triste ») et "
               "laisse « emotions » vide."),
}

DRAFT_JSON = ('Réponds uniquement avec l\'objet JSON des règles : "observations", "changements", '
              '"interactions", "emotions", "description", "appuis", "confiance", "remarque".')
JSON_REMINDER = ('Réponds uniquement avec un objet JSON : '
                 '{"description": "...", "confiance": 0.0 à 1.0, "remarque": "..."}')


# An optional second look at the same images (--seconde-lecture): the model confirms or
# rejects each visual claim it made, before the director reads the passage.
SECOND_LOOK_PROMPT = ("Tu vérifies une audiodescription avant qu'un humain la relise. Regarde les "
                      "images et dis, pour chaque affirmation, si on la voit vraiment : « oui », "
                      "« non » ou « incertain ». Ne réécris rien, n'ajoute rien. Réponds "
                      'uniquement en JSON : {"verifications": [{"affirmation": "...", '
                      '"visible": "oui | non | incertain"}]}')


def _emotion_line(mode: str) -> str:
    return EMOTION_RULES.get(mode, EMOTION_RULES["nuancees"])


def _frames_lines(segment) -> list[str]:
    """Each image with its time, before or during the pause: the model can follow a change."""
    count = len(segment.images)
    instants = list(getattr(segment, "instants", None) or [])
    if not count or len(instants) != count:
        return [(f"Les {count} images jointes sont extraites de ce passage, "
                 "dans l'ordre chronologique.")]
    parts = [f"{i} · {fmt_short(t)} ("
             + ("juste avant la pause, pendant le dialogue" if t < segment.debut
                else "pendant la pause") + ")"
             for i, t in enumerate(instants, 1)]
    return ["Images jointes, dans l'ordre chronologique : " + " ; ".join(parts) + "."]


def _lexicon_line(lexique: dict[str, str] | None) -> list[str]:
    if not lexique:
        return []
    pairs = " ; ".join(f"{thing} → {word}" for thing, word in lexique.items())
    return [f"Lexique du film, à reprendre tel quel : {pairs}"]


def build_draft_prompt(*, film: str, intention_globale: str, style: str, personnages: list[dict],
                       segment, langue: str, story: list[str] | None = None,
                       lexique: dict[str, str] | None = None,
                       exemples: list[str] | None = None, emotions_mode: str = "nuancees",
                       continuite: list[str] | None = None) -> str:
    spec = LANG_SPECS[langue]
    lines = [f"Film : {film}"]
    if intention_globale:
        lines.append(f"Intention du réalisateur : {intention_globale}")
    if style:
        lines.append(f"Style demandé : {style}")
    if personnages:
        people = [f"{p['nom']} ({p['description']})" if p.get("description") else p["nom"]
                  for p in personnages]
        lines.append("Personnages : " + " ; ".join(people))
    lines.extend(_lexicon_line(lexique))
    if exemples:
        lines.append("Exemples écrits pour ce film "
                     "(imite leur langue et leur style, pas leur contenu) :")
        lines.extend(f"- {example}" for example in exemples)
    lines.append(f"Passage : de {fmt_short(segment.debut)} à {fmt_short(segment.fin)} "
                 f"(pause de {segment.duree_parole:.1f} s dans les dialogues).")
    if segment.a_remarquer:
        lines.append(f"À faire remarquer dans ce passage : {segment.a_remarquer}")
    if segment.a_eviter:
        lines.append("À ne jamais mentionner : " + ", ".join(segment.a_eviter))
    if segment.contexte:
        lines.append(f"Contexte de la scène : {segment.contexte}")
    if story:
        lines.append("Ce qui s'est passé avant ce passage, du plus ancien au plus récent "
                     "(dialogues d'après les sous-titres, parfois traduits ; "
                     "ne répète pas ce qui a déjà été décrit) :")
        lines.extend(f"- {line}" for line in story)
    if segment.dialogue_avant:
        lines.append(f"Dialogue juste avant : « {segment.dialogue_avant} »")
    if segment.dialogue_apres:
        lines.append(f"Dialogue juste après : « {segment.dialogue_apres} »")
    if continuite:
        lines.append("Dernier état connu des personnages (ne le redis pas s'il n'a pas changé ; "
                     "décris ce qui change) :")
        lines.extend(f"- {line}" for line in continuite)
    lines.extend(_frames_lines(segment))
    lines.append(_emotion_line(emotions_mode))
    lines.append(f"Langue de sortie : {spec['nom']}. {spec['consigne']}")
    lines.append(f"Nombre maximal de mots : {segment.budget_mots}.")
    lines.append(DRAFT_JSON)
    return "\n".join(lines)


def build_second_look_prompt(*, segment, claims: list[str]) -> str:
    return "\n".join([*_frames_lines(segment), "Affirmations à vérifier sur ces images :",
                      *[f"{i}. {claim}" for i, claim in enumerate(claims, 1)]])


def parse_second_look(raw: str) -> list[dict]:
    """[{affirmation, visible: oui | non | incertain}]; anything unclear counts as incertain."""
    data = _first_object(_FENCE.sub("", (raw or "").strip()))
    items = data.get("verifications") if isinstance(data, dict) else None
    verdicts = {"oui": "oui", "yes": "oui", "visible": "oui", "non": "non", "no": "non"}
    results = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        claim = clean_text(str(item.get("affirmation") or ""))[:200]
        seen = str(item.get("visible") or "").strip().casefold()
        if claim:
            results.append({"affirmation": claim, "visible": verdicts.get(seen, "incertain")})
    return results


def build_revision_prompt(*, draft: str, problems: list[str], budget: int, langue: str,
                          lexique: dict[str, str] | None = None,
                          observations: list[str] | None = None,
                          emotions_mode: str = "nuancees") -> str:
    """A text-only rewrite. It does not see the images again: the signs the model noted on
    them come along, so the rewrite can keep what was seen without inventing the rest."""
    spec = LANG_SPECS[langue]
    seen = (["Signes visibles que tu as notés sur les images (sers-t'en, n'en invente pas "
             "d'autres) : " + " ; ".join(f"{i}. {o}" for i, o in enumerate(observations, 1)),
             ('Ajoute "appuis" à ta réponse : pour chaque phrase, les numéros des signes qui la '
              'fondent ([] si aucun).')] if observations else [])
    return "\n".join([
        f"Voici ton brouillon : « {draft} »",
        "La vérification automatique a trouvé ces problèmes :",
        *[f"- {p}" for p in problems],
        *seen,
        f"Réécris la description pour les corriger, en {budget} mots au maximum, "
        "sans perdre l'information la plus importante.",
        *_lexicon_line(lexique),
        _emotion_line(emotions_mode),
        f"Langue de sortie : {spec['nom']}. {spec['consigne']}",
        JSON_REMINDER,
    ])


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_SPACES = re.compile(r"\s+")


def clean_text(text: str) -> str:
    text = _SPACES.sub(" ", text or "").strip()
    return text.strip('"«» ').strip()


def parse_confidence(value) -> float | None:
    """A confidence between 0 and 1, or None when unknown (which flags the passage).

    Models often drift to a percentage: 30, « 30 % » and « 85% » become 0.30 and 0.85, and a
    French decimal comma (« 0,3 ») is read. Anything else outside 0–1 is unknown: never full
    confidence by accident."""
    if value is None or isinstance(value, bool):
        return None
    percent = False
    if isinstance(value, str):
        text = value.strip()
        percent = text.endswith("%")
        try:
            number = float(text.rstrip("%").strip().replace(",", "."))
        except ValueError:
            return None
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    if percent or 1.0 < number <= 100.0:
        number /= 100.0
    return number if 0.0 <= number <= 1.0 else None


def _first_object(text: str) -> dict | None:
    """The first JSON object in the reply, ignoring any text after it."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    return None


MAX_OBSERVATIONS = 6
MAX_EMOTIONS = 6


def _texts(value, limit: int) -> list[str]:
    """A short list of short strings from whatever the model sent (a string, a list…)."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    kept = [clean_text(str(v))[:200] for v in value
            if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
    return [v for v in kept if v][:limit]


def parse_emotions(value) -> list[dict]:
    """What the model supposes: [{qui, emotion, indices, certitude}], never trusted blindly.
    A bare string becomes an emotion with no evidence; anything unreadable is dropped."""
    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, list):
        return []
    emotions = []
    for item in value[:MAX_EMOTIONS]:
        if isinstance(item, str):
            item = {"emotion": item}
        if not isinstance(item, dict):
            continue
        emotion = clean_text(str(item.get("emotion") or item.get("émotion") or ""))[:80]
        if not emotion:
            continue
        emotions.append({
            "qui": clean_text(str(item.get("qui") or item.get("personnage") or ""))[:80],
            "emotion": emotion,
            "indices": _texts(item.get("indices") or item.get("signes"), 4),
            "certitude": parse_confidence(item.get("certitude", item.get("confiance")))})
    return emotions


def _records(value, keys: tuple[str, ...], required: str, limit: int = 6) -> list[dict]:
    """A list of small records with text fields, from whatever the model sent."""
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        record = {k: clean_text(str(item.get(k) or ""))[:160] for k in keys}
        if not record[required]:
            continue
        frames = item.get("images")
        if "images" in item and isinstance(frames, list):
            record["images"] = [int(f) for f in frames
                                if isinstance(f, (int, float)) and not isinstance(f, bool)][:6]
        out.append(record)
    return out


def parse_supports(value) -> list[list[int]]:
    """Per sentence, the observation numbers it rests on: [[1, 2], [3]]. A flat list is one
    sentence; anything else is dropped."""
    if not isinstance(value, list):
        return []
    if value and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        value = [value]
    supports = []
    for entry in value[:12]:
        if isinstance(entry, list):
            supports.append([int(v) for v in entry
                             if isinstance(v, (int, float)) and not isinstance(v, bool)][:8])
    return supports


def structure_problems(data) -> list[str]:
    """What is missing or malformed in a draft reply (logged, and used by the checks)."""
    if not isinstance(data, dict):
        return ["réponse non JSON"]
    problems = []
    for key, kind in (("observations", list), ("emotions", list), ("changements", list),
                      ("interactions", list)):
        if key not in data:
            problems.append(f"« {key} » absent")
        elif not isinstance(data[key], kind):
            problems.append(f"« {key} » n'est pas une liste")
    for e in data.get("emotions") or [] if isinstance(data.get("emotions"), list) else []:
        c = e.get("certitude") if isinstance(e, dict) else None
        if isinstance(c, (int, float)) and not isinstance(c, bool) and not 0 <= c <= 1:
            problems.append("certitude hors de 0 à 1")
            break
    return problems


def parse_reply(raw: str) -> dict:
    """Extract {description, confiance, remarque, observations, emotions} from a model reply,
    JSON or not. observations: visible facts; emotions: what the model supposes from them."""
    text = _FENCE.sub("", (raw or "").strip())
    data = _first_object(text)
    if isinstance(data, dict):
        return {"description": clean_text(str(data.get("description") or "")),
                "confiance": parse_confidence(data.get("confiance", data.get("confidence"))),
                "remarque": clean_text(str(data.get("remarque") or data.get("note") or "")),
                "observations": _texts(data.get("observations"), MAX_OBSERVATIONS),
                "emotions": parse_emotions(data.get("emotions", data.get("émotions"))),
                "changements": _records(data.get("changements"), ("qui", "avant", "apres"),
                                        "apres"),
                "interactions": _records(data.get("interactions"), ("qui", "envers", "geste"),
                                         "geste"),
                "appuis": parse_supports(data.get("appuis")),
                "structure": structure_problems(data)}
    return {"description": clean_text(text), "confiance": None, "remarque": "Réponse non JSON.",
            "observations": [], "emotions": [], "changements": [], "interactions": [],
            "appuis": [], "structure": ["réponse non JSON"]}

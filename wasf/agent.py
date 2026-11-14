"""The describer agent: write -> automatic checks -> revision -> hand-over to a human.

The agent writes the whole track but never publishes anything. For each pause
it writes a description, checks it against the rules (length, the director's
"avoid" list in any spelling, repeated dialogue, refusals, the track's
language, how it names what characters feel), revises it when a text-only
rewrite can fix it, and logs every step. The model reports what it saw (visible
signs) apart from what it supposes (emotions, with their evidence and
certainty), so the director can check one against the other. Passages it is
unsure about are flagged for the director, who checks a random sample of the
others one by one, validates the rest in one click and approves the track.
"""
from __future__ import annotations

import math
import random
import re
from typing import Callable

from .emotions import (DEFAULT_MODE, STRICT_HINTS, check_emotions, check_evidence,
                       describes_people)
from .prompts import (SECOND_LOOK_PROMPT, SYSTEM_PROMPT, build_draft_prompt,
                      build_revision_prompt, build_second_look_prompt, clean_text,
                      parse_reply, parse_second_look)
from .providers import MockProvider, Provider
from .textnorm import (looks_like_refusal, looks_like_standard_arabic, mentions, script_problem,
                       too_similar)

# Words that often signal an interpretation rather than a description: Wasf's earlier list,
# still used word for word when the director picks the « signes » mode (see emotions.py).
INTERPRETATION_HINTS = STRICT_HINTS


def count_words(text: str) -> int:
    return len((text or "").split())


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", (text or "").lower()) if len(w) > 2}


def run_checks(text: str, *, budget: int, avoid: list[str], dialogue: str,
               langue: str, previous: str = "", emotions_mode: str = DEFAULT_MODE,
               emotions: list[dict] | None = None, ai_text: bool = True,
               names: list[str] | None = None, evidence: dict | None = None) -> list[dict]:
    """Rules every description must pass. 'erreur' blocks validation; 'attention' does not.

    previous: the text of the passage before, to catch a description that repeats it.
    emotions_mode, emotions, names: how emotions may be named (« nuancees » or « signes »),
    what the model supposed with its certainty, and the character names (emotions.py).
    ai_text: the text is the AI's own; certainty about an emotion or a psychological label
    then blocks it, while in a person's edit it is only flagged.
    evidence: {"observations": [...], "structured": bool} from the model's reply; the text is
    then checked against what the model said it saw (AI text only: a person has the image)."""
    text = (text or "").strip()
    if not text:
        return [{"niveau": "info", "code": "vide",
                 "message": "Rien à décrire : écrivez une description ou ignorez ce passage."}]
    results = []
    if looks_like_refusal(text):
        results.append({"niveau": "erreur", "code": "refus",
                        "message": "Le modèle a refusé de décrire : écrivez la description, "
                                   "ou ignorez ce passage."})
    wrong_script = script_problem(text, langue)
    if wrong_script:
        results.append({"niveau": "erreur", "code": "ecriture", "message": wrong_script})
    words = count_words(text)
    if words > budget:
        results.append({"niveau": "erreur", "code": "trop_long",
                        "message": f"Trop long : {words} mots pour {budget} autorisés."})
    hits = [a for a in avoid if a and mentions(text, a)]
    if hits:
        results.append({"niveau": "erreur", "code": "a_eviter",
                        "message": "Mentionne un élément à éviter : " + ", ".join(hits) + "."})
    described, spoken = _content_words(text), _content_words(dialogue)
    if len(described) >= 4 and spoken and len(described & spoken) / len(described) >= 0.6:
        results.append({"niveau": "erreur", "code": "repetition_dialogue",
                        "message": "Répète le dialogue au lieu de décrire l'image."})
    repeated = too_similar(text, previous)
    results.extend(check_emotions(text, langue=langue, mode=emotions_mode, dialogue=dialogue,
                                  previous="" if repeated else previous, emotions=emotions,
                                  strict=ai_text, names=names))
    if ai_text and evidence is not None:
        results.extend(check_evidence(text, langue=langue,
                                      observations=evidence.get("observations"),
                                      emotions=emotions,
                                      structured=evidence.get("structured", True), names=names,
                                      unconfirmed=evidence.get("non_confirmes"),
                                      supports=evidence.get("appuis")))
    if langue == "aeb" and not wrong_script and looks_like_standard_arabic(text):
        results.append({"niveau": "attention", "code": "arabe_standard",
                        "message": "Ressemble à de l'arabe standard plutôt qu'à de la derja : "
                                   "à vérifier."})
    if repeated:
        results.append({"niveau": "attention", "code": "repetition",
                        "message": "Répète presque mot pour mot le passage précédent."})
    if not any(r["niveau"] == "erreur" for r in results):
        results.insert(0, {"niveau": "ok", "code": "ok", "message": f"{words}/{budget} mots."})
    return results


def has_errors(checks: list[dict]) -> bool:
    return any(c.get("niveau") == "erreur" for c in checks)


# Below this, the model itself says it is unsure: a person should look before it goes out.
LOW_CONFIDENCE = 0.5

# Warnings ('attention') never block a passage, but they keep it out of one-click validation.
WARNING_FLAGS = {"interpretation": "interprétation possible",
                 "arabe_standard": "arabe standard probable",
                 "repetition": "répète le passage précédent",
                 "emotion_incertaine": "émotion incertaine",
                 "emotion_dialogue": "émotion déjà dite par le dialogue",
                 "geste_repete": "geste déjà décrit",
                 "certitude": "émotion affirmée avec certitude",
                 "diagnostic": "étiquette psychologique",
                 "emotion_ambigue": "plusieurs lectures possibles",
                 "sans_preuve": "émotion sans signe donné",
                 "indice_non_observe": "signe non observé",
                 "signe_non_observe": "geste peut-être inventé",
                 "reponse_incomplete": "rien d'observé",
                 "surcharge": "trop de gestes",
                 "signe_non_confirme": "non confirmé à la seconde lecture",
                 "phrase_sans_appui": "phrase sans observation",
                 "voix_trop_longue": "voix trop longue"}


def voice_checks(segment) -> list[dict]:
    """What the last export measured, while the text is still the one it measured: a voice
    that overran its pause or ran into the next one. The final export itself refuses such a
    voice; here the reviewer sees it on the passage, with by how much to shorten it."""
    measured = getattr(segment, "voix_mesuree", None) or {}
    if not measured or (measured.get("texte") or "").strip() != (segment.texte or "").strip():
        return []
    if not (measured.get("deborde") or measured.get("chevauche")):
        return []
    def s(value):
        return f"{float(value or 0):.1f}".replace(".", ",")
    when = (measured.get("quand") or "").replace("T", " à ")[:18]
    speed = (f", accélérée ×{float(measured['acceleration']):.2f}".replace(".", ",")
             if float(measured.get("acceleration") or 1) > 1.0 else "")
    parts = []
    if measured.get("deborde"):
        parts.append(f"{s(measured.get('duree_voix_s'))} s de voix{speed} pour "
                     f"{s(measured.get('duree_disponible_s'))} s disponibles, elle déborde de "
                     f"{s(measured.get('depassement_s'))} s")
    if measured.get("chevauche"):
        parts.append(f"elle chevauche la voix de {measured['chevauche']}")
    return [{"niveau": "attention", "code": "voix_trop_longue",
             "message": f"Voix trop longue à l'export du {when} ({measured.get('moteur', '?')}) : "
                        + " ; ".join(parts) + ". Raccourcissez le texte : l'export final est "
                        "refusé tant que la voix déborde."}]


def refresh_voice_check(segment) -> None:
    """Replace the passage's voice-length warning with the current one (or none)."""
    segment.verifications = [c for c in (segment.verifications or [])
                             if c.get("code") != "voix_trop_longue"] + voice_checks(segment)


def review_flags(segment) -> list[str]:
    """Why the director should look at this passage before validating it. Empty: no alert."""
    checks = segment.verifications or []
    flags = []
    if not (segment.texte or "").strip():
        flags.append("rien de décrit")
    if has_errors(checks):
        flags.append("bloqué par une vérification")
    for check in checks:
        if check.get("niveau") == "attention":
            flag = WARNING_FLAGS.get(check.get("code"), "à vérifier")
            if flag not in flags:
                flags.append(flag)
    if segment.confiance_ia is None:
        if (segment.brouillon_ia or "").strip():
            flags.append("confiance de l'IA inconnue")
    elif segment.confiance_ia < LOW_CONFIDENCE:
        flags.append(f"IA peu sûre ({round(segment.confiance_ia * 100)} %)")
    return flags


def validable_in_one_click(segment) -> bool:
    """An untouched AI text with no alert at all."""
    return (segment.statut == "brouillon" and segment.texte == segment.brouillon_ia
            and not review_flags(segment))


SAMPLE_SHARE = 0.10


def sample_size(clean_count: int) -> int:
    """How many clean passages the director checks one by one before validating the rest in
    one click: 10 %, rounded up, and at least 3 once there are 10 or more."""
    if clean_count <= 0:
        return 0
    size = math.ceil(clean_count * SAMPLE_SHARE)
    return min(clean_count, max(3, size)) if clean_count >= 10 else size


def draw_sample(segments, rng: random.Random | None = None) -> list[str]:
    """Clean passages drawn at random for a one-by-one check, in film order. One click stays
    fast, but never blind: the sample shows whether the passages without alerts hold up."""
    clean = [s.id for s in segments if validable_in_one_click(s)]
    chosen = set((rng or random.SystemRandom()).sample(clean, sample_size(len(clean))))
    return [seg_id for seg_id in clean if seg_id in chosen]


class DescriberAgent:
    def __init__(self, provider: Provider, *, film: str, langue: str, intention_globale: str = "",
                 style: str = "", personnages: list[dict] | None = None,
                 lexique: dict[str, str] | None = None, exemples: list[str] | None = None,
                 max_revisions: int = 2, emotions_mode: str = DEFAULT_MODE,
                 second_look: bool = False, checker: Provider | None = None,
                 log: Callable[[str], None] = print):
        self.provider = provider
        self.film = film
        self.langue = langue
        self.intention_globale = intention_globale
        self.style = style
        self.personnages = personnages or []
        self.lexique = lexique or {}
        self.exemples = exemples or []
        self.max_revisions = max(0, max_revisions)
        self.emotions_mode = emotions_mode
        self.names = [p.get("nom", "") for p in self.personnages]
        # A simulation sends no observations: that is not a fault to flag.
        self.structured = not isinstance(provider, MockProvider)
        # The second look can be taken by another provider's model, less likely to repeat a
        # mistake; a simulation never takes it.
        self.checker = checker or provider
        self.second_look = (second_look and self.structured
                            and not isinstance(self.checker, MockProvider))
        self.log = log

    def _checks(self, segment, text: str, previous: str = "",
                emotions: list[dict] | None = None,
                observations: list[str] | None = None,
                unconfirmed: list[str] | None = None,
                supports: list[list[int]] | None = None) -> list[dict]:
        return run_checks(text, budget=segment.budget_mots, avoid=segment.a_eviter,
                          dialogue=f"{segment.dialogue_avant} {segment.dialogue_apres}",
                          langue=self.langue, previous=previous,
                          emotions_mode=self.emotions_mode, emotions=emotions, ai_text=True,
                          names=self.names,
                          evidence={"observations": observations or [],
                                    "structured": self.structured,
                                    "non_confirmes": unconfirmed or [],
                                    "appuis": supports or []})

    def _second_look(self, segment, images: list[bytes], trace: list[dict]) -> list[dict]:
        """Ask the model to confirm, on the same images, each visual claim it made about people.
        Only when asked for (one more call), and only for a passage that describes people."""
        claims = list(segment.observations_ia)
        claims += [(f"{c['qui']} : " if c.get("qui") else "") + f"{c['avant']} → {c['apres']}"
                   for c in segment.changements_ia if c.get("avant")]
        claims += [f"{i.get('qui') or '?'} envers {i.get('envers') or '?'} : {i['geste']}"
                   for i in segment.interactions_ia]
        claims = claims[:8]
        about_people = (describes_people(segment.texte, self.langue, self.names)
                        or segment.changements_ia or segment.interactions_ia or segment.emotions_ia)
        if not (self.second_look and segment.texte and claims and about_people):
            return []
        meta = {"mode": "verification", "langue": self.langue}
        try:
            results = parse_second_look(self.checker.generate(
                SECOND_LOOK_PROMPT, build_second_look_prompt(segment=segment, claims=claims),
                images, meta))
        except Exception as exc:  # the passage stays as it is; the director still reviews it
            trace.append({"etape": "seconde lecture", "erreur": str(exc)})
            return []
        trace.append({"etape": "seconde lecture", "resultats": results})
        return results

    def describe(self, segment, images: list[bytes], story: list[str] | None = None,
                 previous: str = "", continuity: list[str] | None = None) -> bool:
        """Fill segment.brouillon_ia, texte, observations_ia, emotions_ia, verifications and
        journal_agent. Returns False when the provider gave no draft at all (the passage is
        then empty and flagged), True otherwise.

        story: what happened before this pause (see story.story_so_far), past only.
        previous: the description of the passage before, to catch repeats.
        continuity: what each named character last showed (continuity.character_memory).
        """
        meta = {"mode": "brouillon", "langue": self.langue, "budget": segment.budget_mots,
                "a_remarquer": segment.a_remarquer, "a_eviter": segment.a_eviter}
        prompt = build_draft_prompt(film=self.film, intention_globale=self.intention_globale,
                                    style=self.style, personnages=self.personnages,
                                    segment=segment, langue=self.langue, story=story,
                                    lexique=self.lexique, exemples=self.exemples,
                                    emotions_mode=self.emotions_mode, continuite=continuity)
        trace: list[dict] = []
        try:
            parsed = parse_reply(self.provider.generate(SYSTEM_PROMPT, prompt, images, meta))
        except Exception as exc:  # keep going: the describer can write this one by hand
            segment.journal_agent = [{"etape": "erreur", "message": str(exc)}]
            segment.verifications = [{"niveau": "erreur", "code": "fournisseur",
                                      "message": "Aucun brouillon : le fournisseur d'IA a échoué."}]
            self.log(f"  {segment.id} : échec du fournisseur ({exc})")
            return False
        text = parsed["description"]
        # What the model saw stays apart from what it supposes; the text-only revisions never
        # see the images again, so they keep the draft's observations.
        observations, feelings = parsed["observations"], parsed["emotions"]
        supports = parsed["appuis"]
        trace.append({"etape": "brouillon", "texte": text, "confiance": parsed["confiance"],
                      "remarque": parsed["remarque"], "observations": observations,
                      "emotions": feelings, "changements": parsed["changements"],
                      "interactions": parsed["interactions"]})
        if parsed["structure"] and self.structured:
            trace.append({"etape": "structure", "problemes": parsed["structure"]})

        for attempt in range(1, self.max_revisions + 1):
            checks = self._checks(segment, text, previous, feelings, observations,
                                  supports=supports)
            trace.append({"etape": f"verification {attempt}", "resultats": checks})
            problems = [c["message"] for c in checks if c["niveau"] == "erreur"]
            if not problems:
                break
            if any(c["code"] == "refus" for c in checks):
                # A text-only rewrite cannot see the images: it would invent the scene.
                trace.append({"etape": "refus", "message": "Pas de révision : le modèle a "
                                                           "refusé, un humain écrit ce passage."})
                break
            prompt = build_revision_prompt(draft=text, problems=problems,
                                           budget=segment.budget_mots, langue=self.langue,
                                           lexique=self.lexique, observations=observations,
                                           emotions_mode=self.emotions_mode)
            try:  # text-only call: cheaper and less energy than sending the images again
                revised = parse_reply(self.provider.generate(
                    SYSTEM_PROMPT, prompt, None, {**meta, "mode": "revision", "brouillon": text}))
            except Exception as exc:
                trace.append({"etape": "erreur", "message": str(exc)})
                break
            text = revised["description"]
            parsed["confiance"] = revised["confiance"]
            supports = revised["appuis"]  # the draft's would point at sentences that changed
            trace.append({"etape": f"revision {attempt}", "texte": text,
                          "confiance": revised["confiance"]})

        segment.brouillon_ia = clean_text(text)
        segment.texte = segment.brouillon_ia
        segment.confiance_ia = parsed["confiance"]
        segment.observations_ia = observations
        segment.emotions_ia = feelings
        segment.changements_ia = parsed["changements"]
        segment.interactions_ia = parsed["interactions"]
        segment.appuis_ia = supports
        segment.seconde_lecture = self._second_look(segment, images, trace)
        segment.verifications = self._checks(
            segment, segment.texte, previous, feelings, observations,
            [r["affirmation"] for r in segment.seconde_lecture if r["visible"] == "non"],
            supports)
        segment.journal_agent = trace
        segment.statut = "brouillon"
        return True

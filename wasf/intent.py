
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .emotions import DEFAULT_MODE, MODES
from .textnorm import normalize
from .timecode import parse_tc

LANGUAGES = {"fr": "français", "ar": "arabe standard", "aeb": "derja tunisienne"}


class IntentError(ValueError):
    """The intent file is missing a field or contains an invalid value."""


class RightsError(PermissionError):
    """The producer's permission is missing: Wasf refuses to process the film."""


@dataclass
class Scene:
    debut: float
    fin: float
    a_remarquer: str = ""
    a_eviter: list[str] = field(default_factory=list)
    contexte: str = ""


@dataclass
class Intent:
    film: str
    realisateur: str = ""
    langue: str = ""          # empty: the track takes the language of the film's dialogue
    descripteur: str = ""
    accord_producteur: bool = False
    reference_accord: str = ""
    personnages: list[dict] = field(default_factory=list)
    intention_globale: str = ""
    style: str = ""
    scenes: list[Scene] = field(default_factory=list)
    mots_par_seconde: float | None = None
    lexique: dict[str, str] = field(default_factory=dict)   # thing -> the film's own word for it
    exemples: list[str] = field(default_factory=list)       # lines written by the describer
    emotions: str = DEFAULT_MODE    # nuancees: a probable emotion, with its signs · signes: signs only

    def notes_for(self, start: float, end: float) -> dict:
        """Merge the notes of every scene that overlaps [start, end]."""
        must, avoid, context = [], [], []
        for scene in self.scenes:
            if scene.debut < end and scene.fin > start:
                if scene.a_remarquer:
                    must.append(scene.a_remarquer)
                avoid.extend(scene.a_eviter)
                if scene.contexte:
                    context.append(scene.contexte)
        avoided = {a for a in avoid if a}
        # A word to avoid is avoided in the film's own words too, when the lexicon gives them:
        # the director writes "lettre", the Derja track must not say it either.
        wanted = {a.casefold() for a in avoided}
        avoided |= {word for thing, word in self.lexique.items() if thing.casefold() in wanted}
        return {
            "a_remarquer": " ".join(must),
            "a_eviter": sorted(avoided),
            "contexte": " ".join(context),
        }

    def check_rights(self) -> None:
        """The producer's permission, and where to find it: both are required."""
        if not self.accord_producteur:
            raise RightsError(
                "Wasf ne traite un film qu'avec l'accord du producteur. Dans le fichier "
                "d'intention, renseignez « droits: accord_producteur: true » et la "
                "« reference » de l'accord (courriel, contrat…)."
            )
        if not self.reference_accord.strip():
            raise RightsError(
                "L'accord du producteur n'a pas de référence. Sous « droits », renseignez "
                "« reference » : le courriel ou le contrat qui le prouve. Elle est reprise dans le "
                "rapport et les crédits, pour que l'accord puisse être retrouvé."
            )


MAX_EXEMPLES = 12   # enough to set the tone without crowding the prompt


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in value if str(v).strip()]


def _as_lexicon(value) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise IntentError("« lexique » doit associer chaque chose au mot du film, "
                          "par exemple « chéchia: الشاشية ».")
    return {str(thing).strip(): str(word).strip() for thing, word in value.items()
            if str(thing).strip() and word is not None and str(word).strip()}


def _as_consent(droits) -> tuple[bool, str]:
    """(permission given, its reference) from the « droits » section. Only YAML's true counts as
    a yes: any other word, even « oui », is refused, so that « non » or a typo never passes for
    the producer's permission (in Python, every non-empty text counts as true)."""
    if droits is None:
        return False, ""
    if not isinstance(droits, dict):
        raise IntentError("« droits » doit contenir deux lignes : « accord_producteur: true » et "
                          "« reference: » suivie du courriel ou du contrat qui prouve l'accord.")
    given = droits.get("accord_producteur")
    if given is None:
        given = False
    if not isinstance(given, bool):
        raise IntentError(f"« accord_producteur » vaut « {given} » : écrivez true si le "
                          "producteur a donné son accord, false sinon, sans guillemets. Aucun "
                          "autre mot n'est accepté, même « oui » ou « non », pour qu'une faute "
                          "de frappe ne passe jamais pour un accord.")
    return given, str(droits.get("reference") or "").strip()


def _as_emotion_mode(value) -> str:
    if value is None or not str(value).strip():
        return DEFAULT_MODE
    mode = normalize(str(value)).strip()          # « nuancées » or « Nuancees » both work
    if mode not in MODES:
        choices = " ; ".join(f"« {name} » : {meaning}" for name, meaning in MODES.items())
        raise IntentError(f"« emotions » vaut « {value} » : choisir {choices}.")
    return mode


def load_intent(path: Path) -> Intent:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise IntentError(f"Fichier d'intention illisible : {exc}") from exc
    if not isinstance(data, dict):
        raise IntentError("Le fichier d'intention doit contenir des champs « clé: valeur ».")

    film = str(data.get("film") or "").strip()
    if not film:
        raise IntentError("Champ « film » manquant dans le fichier d'intention.")
    langue = str(data.get("langue") or "").strip().lower()
    if langue and langue not in LANGUAGES:
        raise IntentError(f"Langue « {langue} » inconnue : choisir parmi {', '.join(LANGUAGES)}.")

    scenes = []
    for i, raw in enumerate(data.get("scenes") or [], start=1):
        if not isinstance(raw, dict):
            raise IntentError(f"Scène {i} : format invalide.")
        try:
            debut, fin = parse_tc(raw["debut"]), parse_tc(raw["fin"])
        except (KeyError, ValueError) as exc:
            raise IntentError(f"Scène {i} : « debut » et « fin » sont obligatoires ({exc}).") from exc
        if fin <= debut:
            raise IntentError(f"Scène {i} : « fin » doit être après « debut ».")
        scenes.append(Scene(debut, fin, str(raw.get("a_remarquer") or "").strip(),
                            _as_list(raw.get("a_eviter")), str(raw.get("contexte") or "").strip()))

    personnages = [
        {"nom": str(p["nom"]).strip(), "description": str(p.get("description") or "").strip()}
        for p in data.get("personnages") or [] if isinstance(p, dict) and p.get("nom")
    ]
    accord, reference = _as_consent(data.get("droits"))
    mps = data.get("mots_par_seconde")
    return Intent(
        film=film,
        realisateur=str(data.get("realisateur") or "").strip(),
        langue=langue,
        descripteur=str(data.get("descripteur") or "").strip(),
        accord_producteur=accord,
        reference_accord=reference,
        personnages=personnages,
        intention_globale=str(data.get("intention_globale") or "").strip(),
        style=str(data.get("style") or "").strip(),
        scenes=scenes,
        mots_par_seconde=float(mps) if mps else None,
        lexique=_as_lexicon(data.get("lexique")),
        exemples=_as_list(data.get("exemples"))[:MAX_EXEMPLES],
        emotions=_as_emotion_mode(data.get("emotions")),
    )

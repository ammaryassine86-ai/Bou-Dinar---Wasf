"""projet.json: the single file shared by the agent, the review editor and the renderer."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
STATUSES = ("brouillon", "modifie", "valide", "ignore")


@dataclass
class Segment:
    id: str
    debut: float            # start of the pause in the dialogue
    fin: float              # end of the pause
    parole_debut: float     # the voice may start here (start + margin)
    parole_fin: float       # and must stop here (end - margin)
    budget_mots: int        # maximum words that fit, at the language's speaking rate
    source: str = "sous-titres"
    images: list[str] = field(default_factory=list)
    instants: list[float] = field(default_factory=list)  # time of each image (before the pause too)
    dialogue_avant: str = ""
    dialogue_apres: str = ""
    a_remarquer: str = ""
    a_eviter: list[str] = field(default_factory=list)
    contexte: str = ""
    brouillon_ia: str = ""          # the agent's proposal, never edited (transparency)
    confiance_ia: float | None = None
    observations_ia: list[str] = field(default_factory=list)  # what the model says it saw
    emotions_ia: list[dict] = field(default_factory=list)     # what it supposes, on which signs
    changements_ia: list[dict] = field(default_factory=list)  # who changed, from what to what
    interactions_ia: list[dict] = field(default_factory=list) # who did what toward whom
    seconde_lecture: list[dict] = field(default_factory=list) # claims confirmed on a second look
    appuis_ia: list[list[int]] = field(default_factory=list)  # per sentence: observations it rests on
    texte: str = ""                 # the text the describer signs
    statut: str = "brouillon"       # brouillon | modifie | valide | ignore
    verifications: list[dict] = field(default_factory=list)
    journal_agent: list[dict] = field(default_factory=list)
    note: str = ""
    valide_par: str = ""
    valide_le: str = ""
    valide_en_lot: bool = False     # validated in one click with the other passages without alerts
    # The voice as last measured by an export: for which text and engine, how long it lasted
    # (after acceleration), how much time the pause gave it, and by how much it overran.
    voix_mesuree: dict = field(default_factory=dict)
    # Where the AI's draft stands: « a_faire » (not asked yet), « fait », « echec » (the provider
    # failed). Empty in projects made before checkpoints existed.
    etat_ia: str = ""

    @property
    def duree_parole(self) -> float:
        return max(0.0, self.parole_fin - self.parole_debut)


@dataclass
class Project:
    film: str
    video: str                      # path relative to the project folder
    duree: float
    langue: str
    fournisseur: str
    modele: str                     # the model asked for
    realisateur: str = ""
    descripteur: str = ""
    validation_realisateur: bool = False
    validation_realisateur_le: str = ""
    approuve_par: str = ""          # the director's name at the moment of approval
    accord_producteur: bool = False
    reference_accord: str = ""
    intention_globale: str = ""
    style: str = ""
    personnages: list[dict] = field(default_factory=list)
    lexique: dict = field(default_factory=dict)
    exemples: list[str] = field(default_factory=list)
    emotions: str = "nuancees"      # how emotions may be named: nuancees | signes (emotions.py)
    mots_par_seconde: float = 0.0   # speaking rate behind the word budgets (0: the language's)
    encodage_sous_titres: str = ""  # how the subtitle file was read (utf-8, cp1256…), "" if none
    # The video file's identity at preparation (media.fingerprint): the export compares it, to
    # say when the film was replaced, even by one of the same length. "" in older projects.
    empreinte_film: str = ""
    # The drafting run: {"etat": "en_cours" | "terminee", dates…}. Saved after every passage, so
    # an interrupted run can go on (wasf preparer --reprendre) without paying twice.
    preparation: dict = field(default_factory=dict)
    seconde_lecture: str = ""       # who took the second look: "", "même modèle" or another model
    segments: list[Segment] = field(default_factory=list)
    echantillon: list[str] = field(default_factory=list)  # checked one by one before one click
    modeles_utilises: list[str] = field(default_factory=list)  # the models the API said answered
    energie: dict = field(default_factory=dict)
    historique: list[dict] = field(default_factory=list)
    cree_le: str = ""
    version_schema: int = SCHEMA_VERSION
    wasf_version: str = ""

    @property
    def preparation_en_cours(self) -> bool:
        """Drafting started and did not finish (still running, or interrupted)."""
        return (self.preparation or {}).get("etat") == "en_cours"

    @property
    def signataire(self) -> str:
        """Who signs the passages: the describer when there is one, otherwise the director."""
        return (self.descripteur or "").strip() or (self.realisateur or "").strip()

    @property
    def signataires_valides(self) -> list[str]:
        """Who actually validated the passages that will be spoken, in order of first signature.

        The AI notice is built from these signatures, never from the name fields, which anyone
        can retype after the fact."""
        names: list[str] = []
        for seg in self.segments:
            name = (seg.valide_par or "").strip()
            if seg.statut == "valide" and name and name not in names:
                names.append(name)
        return names

    @property
    def mode_signature(self) -> str:
        """'audiodescripteur' when the describer signed every validated passage (or, before any
        signature, when there is a describer), otherwise 'realisation'."""
        describer = (self.descripteur or "").strip()
        names = self.signataires_valides
        if describer and (not names or names == [describer]):
            return "audiodescripteur"
        return "realisation"

    def segment(self, seg_id: str) -> Segment:
        for seg in self.segments:
            if seg.id == seg_id:
                return seg
        raise KeyError(seg_id)

    def log(self, action: str, **details) -> None:
        self.historique.append({"quand": now_iso(), "action": action, **details})


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _known(cls, data: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


def save_project(project: Project, path: Path) -> Path:
    """Atomic and durable write: the editor and the CLI never see a half-written file, and a
    crash, a Ctrl+C or a power cut leaves either the previous file or the new one, whole.

    The new content goes to a temporary file in the same folder, is forced to disk (fsync),
    then replaces the old file in one step (os.replace); the folder is synced too, so the
    replacement itself survives a power cut. If anything fails, the temporary file is removed
    and the previous projet.json is untouched."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(project), ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".projet-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _sync_folder(path.parent)
    return path


def _sync_folder(folder: Path) -> None:
    """Make a rename durable (POSIX). Windows has no folder handle to sync: os.replace there is
    still atomic, only the last instant before a power cut is not guaranteed."""
    if os.name != "posix":
        return
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class ProjectFileError(ValueError):
    """projet.json cannot be read. The message says which file, what is wrong in it and where
    its backups are; the file itself is left exactly as it is."""


def _unreadable(path: Path, why: str) -> ProjectFileError:
    backups = sorted(path.parent.glob("sauvegarde-*/projet.json"))
    if backups:
        names = ", ".join(b.relative_to(path.parent).as_posix() for b in backups[-3:])
        advice = f"Sauvegardes de ce projet, qui s'ouvrent dans l'éditeur : {names}."
    else:
        advice = ("Aucune sauvegarde « sauvegarde-… » dans ce dossier : remettez une copie de "
                  "projet.json, ou refaites la préparation.")
    return ProjectFileError(f"Projet illisible : {path} ({why}). Il a sans doute été modifié à "
                            f"la main ou mal copié ; Wasf l'a laissé tel quel. {advice}")


def load_project(path: Path) -> Project:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise _unreadable(path, "ce n'est pas du texte UTF-8") from None
    except json.JSONDecodeError as exc:
        raise _unreadable(path, f"JSON invalide à la ligne {exc.lineno}, colonne {exc.colno}") \
            from None
    if not isinstance(data, dict) or not isinstance(data.get("segments", []), list):
        raise _unreadable(path, "ce n'est pas un projet Wasf")
    try:
        segments = [Segment(**_known(Segment, s)) for s in data.get("segments", [])]
        project = Project(**_known(Project, {**data, "segments": []}))
    except (TypeError, AttributeError) as exc:
        raise _unreadable(path, f"champ manquant ou mal formé : {exc}") from None
    project.segments = segments
    return project

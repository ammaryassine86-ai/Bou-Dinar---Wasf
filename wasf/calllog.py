"""Journal des appels aux modèles d'IA : une ligne JSON par appel, dans « appels.jsonl », à côté
de projet.json.

Ce que chaque ligne garde : l'étape (brouillon, révision, vérification), le passage, le fournisseur,
le modèle demandé et celui qui a répondu, le nombre d'images, l'empreinte de la requête, les jetons
et la raison de fin quand l'API les donne, la durée et le résultat. Des jetons que l'API ne donne
pas valent null : ils ne sont jamais estimés. Ce qu'une ligne ne garde jamais : une clé d'API, le
texte des consignes, une image.

Le fichier ne fait que grandir : une préparation reprise (--reprendre) ajoute ses lignes aux
précédentes, et un appel déjà réussi n'y apparaît jamais deux fois, puisqu'il n'est pas refait."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from .project import now_iso

CALL_LOG = "appels.jsonl"

_KEY_VARIABLES = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
_KEY_SHAPES = (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"))
_KEY_PARAMETER = re.compile(r"(key=)[^&\s'\"]+", re.IGNORECASE)
USAGE_FIELDS = ("modele_rendu", "jetons_entree", "jetons_sortie", "fin", "essais")


def without_secrets(text: str, limit: int = 300) -> str:
    """An error message as it may be written down: any API key in it is masked."""
    for variable in _KEY_VARIABLES:
        secret = os.environ.get(variable) or ""
        if len(secret) >= 8:
            text = text.replace(secret, "***")
    text = _KEY_PARAMETER.sub(r"\1***", text)
    for shape in _KEY_SHAPES:
        text = shape.sub("***", text)
    return text[:limit]


def request_fingerprint(system: str, user: str, images: list[bytes] | None) -> str:
    """Two identical requests (same instructions, same images) have the same fingerprint: enough
    to spot a call paid twice, without keeping the text or the images."""
    digest = hashlib.sha256()
    for part in (system or "", user or ""):
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    for image in images or []:
        digest.update(hashlib.sha256(image).digest())
    return "sha256:" + digest.hexdigest()


class CallLog:
    """Appends one line per call. Numbering goes on from the lines already in the file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._next: int | None = None

    def _number(self) -> int:
        if self._next is None:
            try:
                with self.path.open(encoding="utf-8") as handle:
                    self._next = sum(1 for line in handle if line.strip()) + 1
            except FileNotFoundError:
                self._next = 1
        number, self._next = self._next, self._next + 1
        return number

    def record(self, entry: dict) -> dict:
        line = {"id": f"a{self._number():04d}", "quand": now_iso(), **entry}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return line

    def watch(self, provider):
        """The provider, with every call written down. None stays None."""
        if provider is None or isinstance(provider, LoggedProvider):
            return provider
        return LoggedProvider(provider, self)


class LoggedProvider:
    """A provider whose every call leaves a line in the log. Everything else (name, model, the
    models seen, its messages) is the provider's own."""

    _OWN = ("wrapped", "_log")

    def __init__(self, inner, log: CallLog):
        self.wrapped = inner          # read by providers.unwrapped
        self._log = log

    def __getattr__(self, name):
        if name in self._OWN:         # not set yet: never look for it on the provider
            raise AttributeError(name)
        return getattr(self.wrapped, name)

    def __setattr__(self, name, value):
        # Anything set on the wrapper (a message channel, a test's marker) is set on the
        # provider itself, which is the one that reads it.
        if name in self._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self.wrapped, name, value)

    def generate(self, system, user, images=None, meta=None):
        meta = meta or {}
        inner = self.wrapped
        inner.last_call = {}
        entry = {"etape": meta.get("mode") or "appel", "passage": meta.get("passage"),
                 "fournisseur": inner.name, "modele_demande": inner.model,
                 "images": len(images or []), "entree": request_fingerprint(system, user, images)}
        start = time.monotonic()
        try:
            text = inner.generate(system, user, images, meta)
        except BaseException as exc:
            cause = exc.__cause__ or exc
            entry.update(_usage(inner), duree_s=round(time.monotonic() - start, 3),
                         statut="interrompu" if isinstance(exc, KeyboardInterrupt) else "erreur",
                         erreur=without_secrets(f"{type(cause).__name__} : {exc}"),
                         statut_http=_http_status(cause), fatal=bool(getattr(exc, "fatal", False)))
            self._write(entry)
            raise
        entry.update(_usage(inner), duree_s=round(time.monotonic() - start, 3), statut="ok")
        self._write(entry)
        return text

    def _write(self, entry: dict) -> None:
        try:
            self._log.record(entry)
        except OSError as exc:  # a full disk must not stop the film: the run goes on
            self.wrapped.notify(f"Journal des appels : écriture impossible ({exc}).")


def _usage(provider) -> dict:
    seen = getattr(provider, "last_call", None) or {}
    return {field: seen.get(field) for field in USAGE_FIELDS}


def _http_status(exc: BaseException) -> int | None:
    from .providers import _status
    return _status(exc)


def summarize(path: Path) -> dict:
    """Totals over the whole log: calls, failures, tokens (only those the APIs gave), seconds."""
    totals = {"appels": 0, "echecs": 0, "jetons_entree": 0, "jetons_sortie": 0,
              "appels_sans_jetons": 0, "duree_s": 0.0, "coupees": 0}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return totals
    for line in lines:
        if not line.strip():
            continue
        try:
            call = json.loads(line)
        except json.JSONDecodeError:
            continue
        totals["appels"] += 1
        totals["echecs"] += call.get("statut") != "ok"
        totals["duree_s"] += float(call.get("duree_s") or 0)
        totals["coupees"] += call.get("fin") in ("max_tokens", "length", "MAX_TOKENS")
        if isinstance(call.get("jetons_entree"), int) and isinstance(call.get("jetons_sortie"), int):
            totals["jetons_entree"] += call["jetons_entree"]
            totals["jetons_sortie"] += call["jetons_sortie"]
        else:
            totals["appels_sans_jetons"] += 1
    totals["duree_s"] = round(totals["duree_s"], 1)
    return totals


def describe_totals(totals: dict) -> str:
    """One line for the person running Wasf."""
    if not totals["appels"]:
        return "Journal des appels : aucun appel au modèle."
    text = (f"Journal des appels ({CALL_LOG}) : {totals['appels']} appel(s), "
            f"{totals['echecs']} en échec, {str(totals['duree_s']).replace('.', ',')} s d'attente")
    counted = totals["appels"] - totals["appels_sans_jetons"]
    if counted:
        text += (f", {totals['jetons_entree']} jetons envoyés et {totals['jetons_sortie']} reçus "
                 f"sur {counted} appel(s)")
    if totals["appels_sans_jetons"]:
        text += f" ; {totals['appels_sans_jetons']} appel(s) sans compte de jetons"
    if totals["coupees"]:
        text += f" ; {totals['coupees']} réponse(s) coupée(s) par la limite de longueur"
    return text + "."

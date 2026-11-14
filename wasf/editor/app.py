"""Local review editor: the director (or a describer, if the production has one) checks the
AI's track, fixes the flagged passages, checks a random sample of the others one by one,
validates the rest in one click and approves.

Runs on the reviewer's own computer: the film and the texts stay local. Other web pages open
in the same browser must not be able to read or change the project, so every request is
checked, in this order:
1. Host: only a loopback name (127.0.0.1, localhost, ::1). A DNS-rebinding page reaches this
   computer under its own name, which shows up here.
2. Sec-Fetch-Site and Origin, when the browser sends them: only this page's own origin.
3. The session token, a random secret written into the page when it is served, sent back in
   an « X-Wasf-Jeton » header by every API call; a request with a body must be JSON.
The server itself only listens on a loopback address (serve()).
"""
from __future__ import annotations

import hmac
import ipaddress
import secrets
import threading
from dataclasses import asdict
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from ..agent import (count_words, draw_sample, has_errors, review_flags, run_checks,
                     validable_in_one_click, voice_checks)
from ..intent import LANGUAGES
from ..project import ProjectFileError, load_project, now_iso, save_project
from ..timecode import fmt_short
from ..tts import estimated_seconds, speaking_rate

RTL_LANGUAGES = {"ar", "aeb"}
STATUSES = ("brouillon", "modifie", "valide", "ignore")
TOKEN_HEADER = "X-Wasf-Jeton"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class EditorHostError(ValueError):
    """The editor was asked to listen beyond this computer."""


def is_loopback(host: str) -> bool:
    """127.0.0.0/8, ::1 or localhost: names that only this computer can reach."""
    name = (host or "").strip().lower().rstrip(".")
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def host_name(host_header: str) -> str:
    """The name in a Host header: « 127.0.0.1:8765 » → 127.0.0.1, « [::1]:8765 » → ::1."""
    value = (host_header or "").strip()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def check_host(host: str) -> None:
    """Refuse any address other than this computer's own (loopback)."""
    if not is_loopback(host):
        raise EditorHostError(
            f"L'éditeur n'écoute que sur cet ordinateur (127.0.0.1, localhost ou ::1) : "
            f"« {host} » refusé. Il n'a pas de comptes : ouvert sur le réseau, n'importe qui "
            "sur le même Wi-Fi pourrait lire le film et valider des passages.")


def serve(app: Flask, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the editor, reachable from this computer only."""
    check_host(host)
    app.run(host=host, port=port, debug=False)


def create_app(project_path: Path) -> Flask:
    project_path = Path(project_path).resolve()
    if not project_path.exists():
        raise FileNotFoundError(f"Projet introuvable : {project_path}")
    load_project(project_path)     # an unreadable project stops here, with a plain message
    base = project_path.parent
    here = Path(__file__).parent
    app = Flask(__name__, template_folder=str(here / "templates"),
                static_folder=str(here / "static"))
    app.json.ensure_ascii = False
    lock = threading.Lock()
    token = secrets.token_urlsafe(32)   # new at every start; only the served page knows it
    app.config["WASF_JETON"] = token

    def refuse(status: int, message: str):
        return jsonify({"erreur": message}), status

    @app.before_request
    def guard():
        if not is_loopback(host_name(request.host)):
            return refuse(403, "Hôte refusé : l'éditeur ne répond qu'à 127.0.0.1 ou localhost.")
        site = request.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            return refuse(403, "Requête venue d'une autre page web : refusée.")
        origin = request.headers.get("Origin")
        if origin is not None and origin != f"{request.scheme}://{request.host}":
            return refuse(403, "Origine refusée : seule la page de l'éditeur peut s'en servir.")
        if request.path.startswith("/api/") or request.method not in SAFE_METHODS:
            sent = request.headers.get(TOKEN_HEADER, "")
            if not hmac.compare_digest(sent.encode("utf-8"), token.encode("utf-8")):
                return refuse(403, "Jeton de session absent ou invalide : rechargez la page "
                                   "de l'éditeur.")
            if request.method not in SAFE_METHODS and request.content_length \
                    and not request.is_json:
                return refuse(415, "Format refusé : l'éditeur n'accepte que du JSON.")
        return None

    @app.after_request
    def harden(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; "
            "object-src 'none'")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path == "/" or request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def segment_view(seg, project) -> dict:
        data = asdict(seg)
        timed = len(seg.instants) == len(seg.images)
        measured = seg.voix_mesuree or {}
        data.update(mots=count_words(seg.texte), duree_parole=round(seg.duree_parole, 1),
                    # Estimated from the words; the real voice is timed by each export.
                    duree_estimee=round(estimated_seconds(seg.texte, project.langue,
                                                          project.mots_par_seconde or None), 1),
                    voix_a_jour=bool(measured) and (measured.get("texte") or "").strip()
                    == (seg.texte or "").strip(),
                    debut_txt=fmt_short(seg.debut), fin_txt=fmt_short(seg.fin),
                    signalements=review_flags(seg), echantillon=seg.id in project.echantillon,
                    images_info=[{"src": src,
                                  "quand": fmt_short(seg.instants[i]) if timed else "",
                                  "avant": timed and seg.instants[i] < seg.debut}
                                 for i, src in enumerate(seg.images)])
        return data

    def pending_sample(project) -> list[str]:
        """Passages of the random sample the director has not validated (or ignored) yet."""
        open_ids = {s.id for s in project.segments if s.statut not in ("valide", "ignore")}
        return [seg_id for seg_id in project.echantillon if seg_id in open_ids]

    def ensure_sample(project) -> bool:
        """Draw the random sample if the project has none yet (projects made before it)."""
        if project.echantillon:
            return False
        project.echantillon = draw_sample(project.segments)
        if project.echantillon:
            project.log("echantillon", passages=project.echantillon)
        return bool(project.echantillon)

    def summary(project) -> dict:
        data = asdict(project)
        data.pop("segments")
        data.pop("historique")
        pending = [s for s in project.segments if s.statut not in ("valide", "ignore")]
        sample = pending_sample(project)
        return {"projet": data,
                "signataire": project.signataire,
                "compteurs": {s: sum(seg.statut == s for seg in project.segments) for s in STATUSES},
                "sans_alerte": sum(validable_in_one_click(s) and s.id not in sample for s in pending),
                "echantillon": sample,
                "a_verifier": sum(bool(review_flags(s)) for s in pending),
                "langue_nom": LANGUAGES.get(project.langue, project.langue),
                "rtl": project.langue in RTL_LANGUAGES,
                "simulation": project.fournisseur == "mock",
                "mots_par_seconde": speaking_rate(project.langue, project.mots_par_seconde or None),
                "preparation_en_cours": project.preparation_en_cours,
                "fichier": str(project_path)}

    def previous_text(project, seg) -> str:
        """The last description spoken before this passage (for the repeat check)."""
        index = next(i for i, other in enumerate(project.segments) if other is seg)
        for other in reversed(project.segments[:index]):
            if other.statut != "ignore" and (other.texte or "").strip():
                return other.texte
        return ""

    def recheck(project, seg) -> None:
        # Certainty about an emotion blocks the AI's own text; in a person's edit it is a
        # warning: the director may know the character better than the rules do.
        seg.verifications = run_checks(seg.texte, budget=seg.budget_mots, avoid=seg.a_eviter,
                                       dialogue=f"{seg.dialogue_avant} {seg.dialogue_apres}",
                                       langue=project.langue,
                                       previous=previous_text(project, seg),
                                       emotions_mode=project.emotions, emotions=seg.emotions_ia,
                                       ai_text=seg.texte.strip() == seg.brouillon_ia.strip(),
                                       names=[p.get("nom", "") for p in project.personnages],
                                       evidence={"observations": seg.observations_ia,
                                                 "structured": project.fournisseur != "mock",
                                                 "non_confirmes": [
                                                     r["affirmation"] for r in seg.seconde_lecture
                                                     if r.get("visible") == "non"],
                                                 "appuis": seg.appuis_ia}) + voice_checks(seg)

    NO_SIGNER = ("Indiquez d'abord le nom de la réalisation (ou de l'audiodescripteur·rice) "
                 "en haut de la page : c'est la personne qui signe.")
    PREPARING = ("La préparation de ce projet est en cours ou a été interrompue : la relecture "
                 "est en lecture seule jusqu'à ce qu'elle se termine (wasf preparer … "
                 "--reprendre), pour qu'aucune modification ne soit perdue.")

    @app.errorhandler(ProjectFileError)
    def unreadable_project(exc):   # damaged while the editor is open: say so on the page
        return jsonify({"erreur": str(exc)}), 500

    @app.get("/")
    def index():
        return render_template("index.html", jeton=token)

    @app.get("/api/projet")
    def get_project():
        with lock:
            project = load_project(project_path)
            if not project.preparation_en_cours and ensure_sample(project):
                save_project(project, project_path)
        return jsonify({**summary(project),
                        "segments": [segment_view(s, project) for s in project.segments]})

    @app.post("/api/projet")
    def update_project():
        body = request.get_json(silent=True) or {}
        with lock:
            project = load_project(project_path)
            if project.preparation_en_cours:
                return jsonify({"erreur": PREPARING}), 409
            notice = ""
            renamed = []
            for name_field, action in (("descripteur", "signature"),
                                       ("realisateur", "signature_realisation")):
                if name_field in body:
                    value = " ".join(str(body[name_field]).split())[:120]
                    if value != getattr(project, name_field):
                        renamed.append(name_field)
                    setattr(project, name_field, value)
                    project.log(action, **{name_field: value})
            # The approval belongs to the person who gave it: a new name withdraws it.
            if renamed and project.validation_realisateur:
                project.validation_realisateur = False
                project.validation_realisateur_le = ""
                project.approuve_par = ""
                project.log("approbation_realisation_annulee", raison="nom modifié")
                notice = ("Approbation retirée : un nom a changé. La réalisation doit "
                          "approuver à nouveau la piste.")
            if "validation_realisateur" in body:
                wanted = bool(body["validation_realisateur"])
                if wanted:
                    pending = [s.id for s in project.segments if s.statut not in ("valide", "ignore")]
                    if pending:
                        return jsonify({"erreur": "Validez ou ignorez d'abord tous les passages "
                                                  f"({len(pending)} restant(s))."}), 409
                    if not project.realisateur.strip():
                        return jsonify({"erreur": "Indiquez d'abord le nom de la réalisation : "
                                                  "c'est elle qui approuve la piste."}), 409
                project.validation_realisateur = wanted
                project.validation_realisateur_le = now_iso() if wanted else ""
                project.approuve_par = project.realisateur if wanted else ""
                project.log("approbation_realisation", valeur=wanted, par=project.realisateur)
            save_project(project, project_path)
            return jsonify({**summary(project), **({"avis": notice} if notice else {})})

    @app.post("/api/passage/<seg_id>")
    def update_segment(seg_id: str):
        body = request.get_json(silent=True) or {}
        action = body.get("action", "enregistrer")
        if action not in ("enregistrer", "valider", "ignorer", "rouvrir"):
            return jsonify({"erreur": f"Action inconnue : {action}"}), 400
        with lock:
            project = load_project(project_path)
            if project.preparation_en_cours:
                return jsonify({"erreur": PREPARING}), 409
            try:
                seg = project.segment(seg_id)
            except KeyError:
                abort(404)
            changed = False
            if "texte" in body:
                text = " ".join(str(body["texte"]).split())
                changed = text != seg.texte
                seg.texte = text
            if "note" in body:
                seg.note = str(body["note"]).strip()[:500]
            recheck(project, seg)
            edited_state = "modifie" if seg.texte != seg.brouillon_ia else "brouillon"
            signer = project.signataire

            if action == "valider":
                if not signer:
                    return jsonify({"erreur": NO_SIGNER}), 409
                if not seg.texte:
                    return jsonify({"erreur": "Texte vide : écrivez une description ou ignorez "
                                              "ce passage."}), 409
                if has_errors(seg.verifications):
                    errors = " ".join(c["message"] for c in seg.verifications if c["niveau"] == "erreur")
                    if changed:  # keep the describer's text, even if it cannot be signed yet
                        seg.statut, seg.valide_par, seg.valide_le = edited_state, "", ""
                    save_project(project, project_path)
                    return jsonify({"erreur": f"Corrigez d'abord : {errors}",
                                    "passage": segment_view(seg, project)}), 409
                seg.statut, seg.valide_par, seg.valide_le = "valide", signer, now_iso()
                seg.valide_en_lot = False
            elif action == "ignorer":
                seg.statut, seg.valide_par, seg.valide_le = "ignore", signer, now_iso()
                seg.valide_en_lot = False
            elif action == "rouvrir" or changed:
                seg.statut, seg.valide_par, seg.valide_le = edited_state, "", ""
                seg.valide_en_lot = False

            if (changed or action == "rouvrir") and project.validation_realisateur:
                project.validation_realisateur = False
                project.validation_realisateur_le = ""
                project.approuve_par = ""
                project.log("approbation_realisation_annulee", raison=f"{seg.id} modifié")
            if changed or action != "enregistrer":
                project.log(action, passage=seg.id, par=signer)
            save_project(project, project_path)
            return jsonify({**summary(project), "passage": segment_view(seg, project)})

    @app.post("/api/valider-sans-alerte")
    def validate_without_alerts():
        """One click for every untouched AI text that raised no alert; flagged ones stay.

        Never blind: a random sample of those passages must first be validated one by one."""
        with lock:
            project = load_project(project_path)
            if project.preparation_en_cours:
                return jsonify({"erreur": PREPARING}), 409
            signer = project.signataire
            if not signer:
                return jsonify({"erreur": NO_SIGNER}), 409
            for seg in project.segments:
                if seg.statut == "brouillon":
                    recheck(project, seg)
            ensure_sample(project)
            waiting = pending_sample(project)
            if waiting:
                save_project(project, project_path)
                return jsonify({"erreur": "Avant de valider en un clic, relisez et validez un par "
                                          "un ces passages tirés au hasard : "
                                          + ", ".join(waiting) + ".",
                                "echantillon": waiting}), 409
            done = []
            for seg in project.segments:
                if validable_in_one_click(seg):
                    seg.statut, seg.valide_par, seg.valide_le = "valide", signer, now_iso()
                    seg.valide_en_lot = True
                    done.append(seg.id)
            if done:
                project.log("validation_sans_alerte", passages=done, par=signer)
            save_project(project, project_path)
            return jsonify({**summary(project), "valides": done,
                            "segments": [segment_view(s, project) for s in project.segments]})

    @app.get("/images/<path:name>")
    def image(name: str):
        return send_from_directory(base / "images", name)

    return app

"""Exports: AI disclosure, WebVTT/SRT text tracks, transparency report and credits."""
from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path

from . import __version__
from .agent import count_words
from .emotions import named_emotions
from .project import Project, now_iso
from .timecode import fmt_tc

LABELS = {
    "fr": {"base": "Audiodescription assistée par intelligence artificielle, écrite et validée par {who}.",
           "ia": "Audiodescription écrite par intelligence artificielle, validée par {who}.",
           "director": " Approuvée par la réalisation.",
           "draft": "Version de travail, non validée. Audiodescription générée par intelligence "
                    "artificielle.",
           "direction": "la réalisation",
           "and": " et ",
           "simulation": "Simulation : aucune image n'a été analysée. Ces textes de démonstration "
                         "ne décrivent pas le film.",
           "draft_prefix": "Version de travail, non validée."},
    "ar": {"base": "وصف صوتي بمساعدة الذكاء الاصطناعي، كتبه وراجعه {who}.",
           "ia": "وصف صوتي كتبه الذكاء الاصطناعي وصادق عليه {who}.",
           "director": " وافقت عليه جهة الإخراج.",
           "draft": "نسخة عمل غير مصادق عليها. وصف صوتي مولَّد بالذكاء الاصطناعي.",
           "direction": "فريق الإخراج",
           "and": " و",
           "simulation": "محاكاة: لم تُحلَّل أي صورة. هذه نصوص تجريبية لا تصف الفيلم.",
           "draft_prefix": "نسخة عمل غير مصادق عليها."},
}
LABELS["aeb"] = LABELS["ar"]


def _join(names: list[str], spec: dict) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + spec["and"] + names[-1]


def is_simulation(project: Project) -> bool:
    """The offline mock looks at no image: its texts must never pass for AI descriptions."""
    return project.fournisseur == "mock"


def label_text(project: Project, brouillon: bool = False) -> str:
    """The sentence spoken before the film and written in every export.

    It says who did what, from the signatures on the passages, never from the name fields:
    when the describer signed every passage, the AI assisted and the describer wrote and
    validated; otherwise the AI wrote the track and the people who signed validated it.
    A simulation says it is one.
    """
    spec = LABELS.get(project.langue, LABELS["fr"])
    if is_simulation(project):
        return (spec["draft_prefix"] + " " if brouillon else "") + spec["simulation"]
    if brouillon:  # a working version claims no validation at all
        return spec["draft"]
    if project.mode_signature == "audiodescripteur":
        text = spec["base"].format(who=project.descripteur.strip())
    else:
        who = (_join(project.signataires_valides, spec) or project.realisateur.strip()
               or spec["direction"])
        text = spec["ia"].format(who=who)
    if project.validation_realisateur:
        text += spec["director"]
    return text


def _cue_text(text: str) -> str:
    return text.replace("-->", "→").strip()


def write_vtt(segments, path: Path, label: str) -> Path:
    lines = ["WEBVTT", "", "NOTE", label, f"Généré avec Wasf {__version__}.", ""]
    for seg in segments:
        lines += [seg.id, f"{fmt_tc(seg.parole_debut)} --> {fmt_tc(seg.parole_fin)}",
                  _cue_text(seg.texte), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_srt(segments, path: Path) -> Path:
    blocks = [f"{i}\n{fmt_tc(seg.parole_debut, ',')} --> {fmt_tc(seg.parole_fin, ',')}\n"
              f"{_cue_text(seg.texte)}\n" for i, seg in enumerate(segments, 1)]
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


# What the export checks on the voices (lot 2), by problem code, as the credits name them.
CHECK_NAMES = {"deborde": "voix trop longue pour sa pause",
               "chevauche": "voix qui se chevauchent",
               "muette": "voix muette",
               "ecretage": "son saturé",
               "volume": "écart de volume entre les voix",
               "trop_courte": "voix trop courte pour son texte",
               "silence_debut": "silence au début d'une voix",
               "silence_fin": "silence à la fin d'une voix",
               "hors_film": "passage après la fin du film",
               "coupee": "voix coupée par la fin du film"}


def audio_summary(problems: list[dict]) -> dict:
    """The voice checks of one export, for the report. Says which checks ran, so that « no
    problem » is never read as « no error at all »."""
    blocking = [p for p in problems if p.get("gravite", "bloquant") == "bloquant"]
    counts: dict[str, int] = {}
    for problem in problems:
        counts[problem["code"]] = counts.get(problem["code"], 0) + 1
    if not problems:
        result = "aucun problème trouvé par ces contrôles"
    else:
        result = (f"{len(blocking)} problème(s) bloquant(s), "
                  f"{len(problems) - len(blocking)} alerte(s)")
    return {"controles_faits": list(CHECK_NAMES.values()), "resultat": result,
            "bloquants": len(blocking), "alertes": len(problems) - len(blocking),
            "par_type": counts, "problemes": problems}


def transparency_report(project: Project, placed: list[dict], brouillon: bool,
                        voix: dict | None = None, controles: list[dict] | None = None) -> dict:
    """Who did what: how much of the final text came from the AI, how much a person changed,
    how many passages were validated in one click, who speaks the descriptions, and what the
    voice checks found. Left empty (None) when not measured, never guessed."""
    active = [s for s in project.segments if s.statut != "ignore" and s.texte.strip()]
    with_draft = [s for s in active if s.brouillon_ia.strip()]
    changes = [1 - SequenceMatcher(None, s.brouillon_ia, s.texte).ratio() for s in with_draft]
    mode = project.mode_signature
    validated = [s for s in project.segments if s.statut == "valide"]
    return {
        "film": project.film,
        "genere_le": now_iso(),
        "wasf_version": __version__,
        "mention": label_text(project, brouillon),
        "version_de_travail": brouillon,
        "langue": project.langue,
        "simulation": is_simulation(project),
        "ia": {"fournisseur": project.fournisseur, "modele": project.modele,
               "modeles_utilises": project.modeles_utilises,
               "role":("simulation hors ligne : aucune image analysée" if is_simulation(project)
                        else "propose des brouillons ; ne publie rien" if mode == "audiodescripteur"
                        else "écrit la piste ; rien n'est publié sans la validation de la réalisation")},
        "humains": {"mode": mode,
                    "signataires": project.signataires_valides,
                    "audiodescripteur": project.descripteur,
                    "realisation": project.realisateur,
                    "validation_realisation": project.validation_realisateur,
                    "validation_realisation_le": project.validation_realisateur_le,
                    "approuve_par": project.approuve_par},
        "droits": {"accord_producteur": project.accord_producteur,
                   "reference": project.reference_accord,
                   "entrainement_sur_le_film": False},
        "passages": {
            "total": len(project.segments),
            "valides": len(validated),
            "valides_en_un_clic": sum(s.valide_en_lot for s in validated),
            "valides_un_par_un": sum(not s.valide_en_lot for s in validated),
            "echantillon_tire": len(project.echantillon),
            "echantillon_relu": sum(s.id in project.echantillon and s.statut in ("valide", "ignore")
                                    and not s.valide_en_lot for s in project.segments),
            "ignores": sum(s.statut == "ignore" for s in project.segments),
            "modifies_par_un_humain": sum(s.texte.strip() != s.brouillon_ia.strip() for s in with_draft),
            "ecrits_sans_brouillon": len(active) - len(with_draft),
            "part_moyenne_du_texte_modifiee": round(sum(changes) / len(changes), 3) if changes else None,
            "mots_total": sum(count_words(s.texte) for s in active),
        },
        "emotions": {"mode": project.emotions,
                     "passages_nommant_une_emotion": sum(
                         bool(named_emotions(s.texte, project.langue,
                                             [p.get("nom", "") for p in project.personnages]))
                         for s in active)},
        "seconde_lecture": {"par": project.seconde_lecture or "aucune",
                            "passages_relus": sum(bool(s.seconde_lecture) for s in active),
                            "affirmations_non_confirmees": sum(
                                r.get("visible") == "non" for s in active
                                for r in s.seconde_lecture)},
        "duree_film_s": project.duree,
        "voix_utilisee": voix,
        "voix": placed,
        # Only possible in a working version: the final export refuses a voice that overruns
        # its pause or runs into the next one.
        "voix_hors_pause": [p["id"] for p in placed if p.get("deborde") or p.get("chevauche")],
        "controle_audio": audio_summary(controles) if controles is not None else None,
        "energie": project.energie,
    }


def write_report(report: dict, path: Path) -> Path:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _emotions_line(emotions: dict) -> str:
    if emotions.get("mode") == "signes":
        return "Émotions : seulement leurs signes visibles, à la demande de la réalisation"
    count = emotions.get("passages_nommant_une_emotion")
    return ("Émotions : nommées seulement avec leurs signes visibles, jamais avec certitude"
            + (f" ({count} passage(s))" if count else ""))


def _voice_line(voice: dict | None) -> str:
    if not voice:
        return ""
    line = f"Voix : {voice['libelle']}"
    if voice.get("silences_coupes"):
        line += " ; silence coupé avant et après chaque voix"
    return line


def _audio_line(summary: dict | None) -> str:
    if not summary:
        return ""
    if not summary["problemes"]:
        return f"Contrôle audio : {summary['resultat']}"
    parts = []
    if summary["bloquants"]:
        parts.append(f"{summary['bloquants']} problème(s) bloquant(s)")
    if summary["alertes"]:
        parts.append(f"{summary['alertes']} alerte(s)")
    kinds = ", ".join(CHECK_NAMES.get(code, code) for code in summary["par_type"])
    line = f"Contrôle audio : {' et '.join(parts)} ({kinds})"
    return line + (" : version de travail seulement" if summary["bloquants"] else "")


def write_credits(report: dict, path: Path) -> Path:
    p = report["passages"]
    humans = report["humains"]
    # Name the model the API says answered, not only the one asked for.
    models = report["ia"].get("modeles_utilises") or [report["ia"]["modele"]]
    ai = f"{report['ia']['fournisseur']}, modèle {', '.join(models)}"
    share = p["part_moyenne_du_texte_modifiee"]
    signers = ", ".join(humans["signataires"]) or "(à renseigner)"
    if report.get("simulation"):
        who = [f"Textes : simulation hors ligne ({ai}), aucune image analysée ; "
               f"validés par {signers}"]
    elif humans["mode"] == "audiodescripteur":
        who = [f"Audiodescription : {humans['audiodescripteur']}",
               f"Assistance IA : {ai}, brouillons uniquement"]
    else:
        who = [f"Audiodescription : écrite par IA ({ai}), validée par {signers}"]
    lines = [
        f"Film : {report['film']}",
        f"Mention : {report['mention']}",
        "",
        *who,
        f"Réalisation : {humans['realisation'] or '(à renseigner)'}"
        + (" — piste approuvée" if humans["validation_realisation"] else " — approbation en attente"),
        f"Accord du producteur : {report['droits']['reference'] or 'oui'}",
        _voice_line(report.get("voix_utilisee")),
        _audio_line(report.get("controle_audio")),
        "",
        f"Passages validés : {p['valides']} sur {p['total']} (ignorés : {p['ignores']})",
        (f"dont validés en un clic, sans alerte : {p['valides_en_un_clic']}, après relecture "
         f"d'un échantillon de {p['echantillon_relu']} passage(s) tiré(s) au hasard")
        if p["valides_en_un_clic"] else "",
        f"Passages modifiés par un humain : {p['modifies_par_un_humain']}",
        f"Part moyenne du texte modifiée : {round(share * 100)} %" if share is not None else "",
        _emotions_line(report.get("emotions") or {}),
        "",
        "Le film n'est jamais utilisé pour entraîner un modèle d'IA.",
        f"Généré avec Wasf {report['wasf_version']} le {report['genere_le']}.",
    ]
    path.write_text("\n".join(line for line in lines if line is not None) + "\n", encoding="utf-8")
    return path


def make_card(project: Project, path: Path, width: int, height: int, brouillon: bool) -> Path | None:
    """Title card shown during the spoken disclosure (needs Pillow; otherwise a black card)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    def font(size: int):
        for name in ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "Helvetica.ttc"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    if is_simulation(project):
        title, who = "Simulation : aucune image analysée", "Textes de démonstration, pas une audiodescription"
    elif project.mode_signature == "audiodescripteur":
        title, who = "Audiodescription assistée par IA", f"Écrite et validée par {project.descripteur.strip()}"
    else:
        title = "Audiodescription écrite par IA"
        names = ", ".join(project.signataires_valides)
        who = f"Validée par {names or project.realisateur.strip() or 'la réalisation'}"
    if brouillon:
        who = "Relecture humaine en cours"
    lines = [(title, 0.065, (255, 255, 255)),
             (who, 0.042, (225, 225, 235)),
             ("Approuvée par la réalisation" if project.validation_realisateur
              else "Approbation de la réalisation en attente", 0.034, (190, 190, 205)),
             ("Wasf · IA Éthique 360", 0.03, (150, 150, 170))]
    if brouillon:
        lines.insert(0, ("VERSION DE TRAVAIL — NON VALIDÉE", 0.04, (244, 162, 97)))
    image = Image.new("RGB", (width, height), (14, 14, 22))
    draw = ImageDraw.Draw(image)
    y = height * (0.26 if brouillon else 0.32)
    for text, ratio, color in lines:
        face = font(max(12, int(height * ratio)))
        draw.text(((width - draw.textlength(text, font=face)) / 2, y), text, font=face, fill=color)
        y += height * ratio * 1.9
    image.save(path)
    return path

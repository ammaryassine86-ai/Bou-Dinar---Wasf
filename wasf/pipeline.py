"""The two main steps: prepare (the agent drafts) and render (voice, mix, exports)."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from . import __version__, media
from .agent import DescriberAgent, count_words, draw_sample, refresh_voice_check
from .energy import EnergyMeter
from .export import (label_text, make_card, notice_seconds, transparency_report, write_credits,
                     write_report, write_srt, write_vtt)
from .gaps import ENCODING_NAMES, load_subtitles, neighbours, plan_windows
from .intent import LANGUAGES, load_intent
from .mix import VoiceTimingError, build_mix
from .project import Project, Segment, load_project, now_iso, save_project
from .providers import ProviderError, get_provider
from .continuity import character_memory
from .story import story_so_far
from .textnorm import dialogue_language
from .timecode import fmt_short
from .tts import (RECORDING_EXTENSIONS, WORDS_PER_SECOND, TTSError, describe_voice,
                  find_recording, synthesize)

LANG3 = {"fr": "fra", "ar": "ara", "aeb": "ara"}

# Frames taken just before a pause, during the dialogue, where reactions happen: smaller ones,
# since they only need to show what changed (fewer tokens, less energy).
CONTEXT_FRAME_WIDTH = 512
CANDIDATES = 6     # tiny frames scanned per group to find where the image changes


def _second_reader(choice, model: str | None, provider):
    """Who takes the second look: nobody, the same model, or another provider's model."""
    if choice in (None, False, "", "non"):
        return None, ""
    if choice is True or choice in ("meme", "même"):
        return provider, "même modèle"
    checker = get_provider(str(choice), model)        # fail fast if its key is missing
    return checker, f"{checker.name} ({checker.model})"


def _language_note(langue: str, chosen: str | None, spoken: str | None) -> str:
    """Which language the track is written and voiced in, and why."""
    name = LANGUAGES[langue]
    if not chosen:
        if spoken:
            return (f"Langue de la piste : {name}, comme les dialogues (une autre : « langue » "
                    "dans l'intention ou --langue).")
        return (f"Langue de la piste : {name} par défaut, faute de sous-titres pour reconnaître "
                "celle du film (« langue » dans l'intention ou --langue).")
    if spoken and spoken != langue:
        return (f"Attention : les dialogues semblent en {LANGUAGES[spoken]}, la piste sera en "
                f"{name}. Si ce n'est pas voulu, changez « langue » dans l'intention ou --langue.")
    return f"Langue de la piste : {name}."


def _moments(video: Path, start: float, end: float, count: int, even: list[float],
             adaptive: bool, fps: float | None = None) -> list[float]:
    """The times to show in [start, end): where the image changes most, so a gesture that
    falls between evenly spaced frames is not missed; the even times for a still shot."""
    if not adaptive or count <= 0 or end - start < 0.2:
        return even
    try:
        thumbs = media.thumbnails(video, start, end - start, max(CANDIDATES, count + 1), fps)
    except media.MediaError:
        return even
    return media.most_distinct(thumbs, count) or even


class RenderError(RuntimeError):
    """Export refused (missing validation) or impossible."""


class ProjectExistsError(FileExistsError):
    """A project (and maybe a whole review) already sits in the output folder."""


def _relative(path: Path, start: Path) -> str:
    try:
        return os.path.relpath(path, start)
    except ValueError:  # different drives on Windows
        return str(path)


def _protect_existing(out_dir: Path, remplacer: bool, log: Callable[[str], None]) -> None:
    """Never overwrite a review: refuse, or keep the old project in a dated backup folder."""
    project_file = out_dir / "projet.json"
    if not project_file.exists():
        return
    try:
        old = load_project(project_file)
        validated = sum(s.statut == "valide" for s in old.segments)
    except (OSError, ValueError, TypeError):  # unreadable file: still never overwritten
        old, validated = None, 0
    if not remplacer:
        unfinished = ""
        if old is not None and old.preparation_en_cours:
            left = sum(s.etat_ia == "a_faire" for s in old.segments)
            unfinished = (f" Sa préparation a été interrompue ({left} passage(s) restant(s)) : "
                          "pour la continuer sans repayer ce qui est fait, relancez avec "
                          "--reprendre.")
        raise ProjectExistsError(
            f"Un projet existe déjà dans {out_dir} ({validated} passage(s) validé(s))."
            f"{unfinished} Pour garder cette relecture, choisissez un autre dossier avec "
            "--sortie. Pour repartir de zéro, ajoutez --remplacer : l'ancien projet sera gardé "
            "dans un dossier « sauvegarde-… ».")
    backup = out_dir / f"sauvegarde-{datetime.now():%Y%m%d-%H%M%S}"
    while backup.exists():
        backup = backup.with_name(backup.name + "-bis")
    backup.mkdir(parents=True)
    if (out_dir / "images").exists():
        shutil.move(str(out_dir / "images"), str(backup / "images"))
    if old is None:
        shutil.move(str(project_file), str(backup / "projet.json"))
    else:  # rewrite the video path so the backup still opens in the editor
        old.video = _relative((out_dir / old.video).resolve(), backup)
        old.log("sauvegarde", depuis=str(out_dir))
        save_project(old, backup / "projet.json")
        project_file.unlink()
    log(f"Ancien projet gardé dans {backup} ({validated} passage(s) validé(s)).")


class ResumeError(RuntimeError):
    """--reprendre or --refaire-echecs cannot be applied to this folder."""


def _failed(seg: Segment) -> bool:
    """The AI gave no draft for this passage (provider error, quota…). In projects made before
    the passages' state was recorded, the provider-failure check gives it away."""
    if seg.etat_ia:
        return seg.etat_ia == "echec"
    return not (seg.brouillon_ia or "").strip() and any(
        c.get("code") == "fournisseur" for c in seg.verifications or [])


def _models(project: Project, provider, checker) -> list[str]:
    seen = set(project.modeles_utilises) | provider.models_seen
    return sorted(seen | (checker.models_seen if checker else set()))


def _stop_on_fatal(project: Project, project_file: Path, seg: Segment, exc: ProviderError,
                   provider, checker) -> None:
    """A fatal provider error (refused key, unknown model, used-up quota…): keep every finished
    passage, record why the run stopped, and stop with what to do next. Never returns."""
    seg.etat_ia = "echec"
    project.modeles_utilises = _models(project, provider, checker)
    project.log("arret_fournisseur", passage=seg.id, raison=str(exc))
    save_project(project, project_file)
    written = sum(s.etat_ia == "fait" for s in project.segments)
    left = sum(s.etat_ia == "a_faire" for s in project.segments)
    raise ProviderError(
        f"Préparation arrêtée au passage {seg.id} : {exc}\n"
        "Cette erreur reviendrait à chaque passage : Wasf s'arrête au lieu de tous les essayer. "
        f"{written} passage(s) écrit(s) sont enregistrés dans {project_file}, {left} restent à "
        "faire. Une fois le problème réglé, relancez la même commande avec --reprendre "
        "--refaire-echecs : les passages déjà écrits ne seront pas redemandés à l'IA.",
        fatal=True) from exc


def _draft(project: Project, project_file: Path, todo: list[str], agent: DescriberAgent,
           cues, provider, checker, log: Callable[[str], None]) -> dict:
    """Let the agent draft the passages in `todo`, in film order, and save the project after
    each one (atomically, see save_project). Whatever happens next (Ctrl+C, a crash, a closed
    laptop, a power cut), every finished passage is on disk and is never asked of the AI
    again. Returns the energy measurement of this run."""
    segments, waiting, out_dir = project.segments, set(todo), project_file.parent
    done = 0
    with EnergyMeter("preparation") as meter:
        try:
            for i, seg in enumerate(segments, 1):
                if seg.id not in waiting:
                    continue
                images = [(out_dir / rel).read_bytes() for rel in seg.images]
                # The story so far: earlier dialogue and descriptions, never what comes next.
                earlier = [(s.debut, s.texte) for s in segments[:i - 1] if s.texte]
                try:
                    drafted = agent.describe(seg, images, story_so_far(cues, earlier, seg.debut),
                                             previous=earlier[-1][1] if earlier else "",
                                             continuity=character_memory(segments[:i - 1],
                                                                         agent.names))
                except ProviderError as exc:   # describe() only lets the fatal ones through
                    _stop_on_fatal(project, project_file, seg, exc, provider, checker)
                seg.etat_ia = "fait" if drafted else "echec"
                project.modeles_utilises = _models(project, provider, checker)
                save_project(project, project_file)          # checkpoint after every passage
                done += 1
                log(f"  [{i}/{len(segments)}] {seg.id} {fmt_short(seg.debut)} → {fmt_short(seg.fin)}"
                    f" · {count_words(seg.texte)}/{seg.budget_mots} mots")
        except KeyboardInterrupt:
            left = sum(s.etat_ia == "a_faire" for s in segments)
            log(f"Interrompu : {done} passage(s) écrit(s) pendant cette session sont enregistrés "
                f"dans {project_file}, {left} restent à faire. Relancez la même commande avec "
                "--reprendre : les passages déjà écrits ne seront pas redemandés à l'IA.")
            raise
    return meter.result


def _restore_frames(project: Project, out_dir: Path, video: Path, todo: list[str]) -> None:
    """Frames of the passages still to draft that are missing on disk are extracted again
    (FFmpeg, no AI call), at the times recorded in the project."""
    for seg in project.segments:
        if seg.id not in todo:
            continue
        for k, rel in enumerate(seg.images):
            path = out_dir / rel
            if path.exists():
                continue
            if k >= len(seg.instants):
                raise ResumeError(f"Image manquante pour {seg.id} ({rel}), sans son instant : "
                                  "repartez de zéro avec --remplacer.")
            width = CONTEXT_FRAME_WIDTH if "_avant" in path.name else 768
            media.extract_frame(video, seg.instants[k], path, max_width=width)


def _go_on(out_dir: Path, video: Path, provider, checker, second_label: str,
           chosen: str | None, cues, *, reprendre: bool, refaire_echecs: bool,
           sous_titres: Path | None, max_revisions: int, log: Callable[[str], None]) -> Path:
    """--reprendre / --refaire-echecs: the saved plan (pauses, frames, word budgets) and the
    intent copied into the project are kept; only the passages to do are sent to the AI."""
    project_file = out_dir / "projet.json"
    if not project_file.exists():
        raise ResumeError(f"Aucun projet dans {out_dir} : rien à reprendre. Lancez « wasf "
                          "preparer » sans --reprendre ni --refaire-echecs, ou indiquez le bon "
                          "dossier avec --sortie.")
    project = load_project(project_file)
    planned_for = (out_dir / project.video).resolve()
    if planned_for != video:
        raise ResumeError(f"Le projet de {out_dir} a été préparé pour une autre vidéo "
                          f"({planned_for}).")

    def plan(project: Project) -> tuple[list[str], list[str]]:
        todo = [s.id for s in project.segments if s.etat_ia == "a_faire"] if reprendre else []
        kept = []
        if refaire_echecs:
            for seg in project.segments:
                if seg.id in todo or not _failed(seg):
                    continue
                if seg.statut == "brouillon" and not (seg.texte or "").strip():
                    todo.append(seg.id)
                else:  # written, validated or ignored by a person since the failure: theirs
                    kept.append(seg.id)
        order = {s.id: i for i, s in enumerate(project.segments)}
        return sorted(todo, key=order.get), kept

    todo, kept = plan(project)
    if reprendre and not todo and not refaire_echecs:
        raise ResumeError("Rien à reprendre : toutes les pauses de ce projet ont déjà été "
                          "soumises à l'IA. Pour refaire seulement celles où elle a échoué : "
                          "--refaire-echecs.")
    if kept:
        log("Gardés tels quels, écrits ou traités à la main depuis l'échec : "
            + ", ".join(kept) + ".")
    if not todo:
        log("Aucun passage à refaire : l'IA n'a échoué sur aucun passage encore vide.")
        return project_file
    if chosen and chosen != project.langue:
        log(f"Attention : la piste de ce projet est en {LANGUAGES[project.langue]} et le reste "
            "(--langue ne change pas un projet commencé).")
    if project.encodage_sous_titres and not sous_titres:
        log("Attention : ce projet a été préparé avec des sous-titres. Redonnez --sous-titres "
            "pour que l'agent garde le dialogue d'avant en contexte.")
    _restore_frames(project, out_dir, video, todo)

    # From here the editor and the export refuse changes until the run ends. Read the file
    # again first: the editor may have saved while frames were being restored.
    project = load_project(project_file)
    todo, _ = plan(project)
    for seg in project.segments:
        if seg.id in todo:
            seg.etat_ia = "a_faire"
    project.preparation = {**(project.preparation or {}), "etat": "en_cours",
                           "reprise_le": now_iso()}
    save_project(project, project_file)
    kept_ok = sum(s.id not in todo and s.etat_ia in ("fait", "") for s in project.segments)
    log(f"Reprise : {len(todo)} passage(s) à écrire ({', '.join(todo[:10])}"
        f"{'…' if len(todo) > 10 else ''}) ; {kept_ok} déjà écrit(s), sans nouvel appel à l'IA.")

    agent = DescriberAgent(provider, film=project.film, langue=project.langue,
                           intention_globale=project.intention_globale, style=project.style,
                           personnages=project.personnages, lexique=project.lexique,
                           exemples=project.exemples, max_revisions=max_revisions,
                           emotions_mode=project.emotions, second_look=checker is not None,
                           checker=checker, log=log)
    energy = _draft(project, project_file, todo, agent, cues, provider, checker, log)
    project.energie.setdefault("preparation_reprises", []).append(energy)
    if not project.echantillon:
        project.echantillon = draw_sample(project.segments)
    project.seconde_lecture = project.seconde_lecture or second_label
    project.modeles_utilises = _models(project, provider, checker)
    project.log("reprise" if reprendre else "refaire_echecs", fournisseur=provider.name,
                modele=provider.model, passages=todo, gardes=kept,
                echecs=[s.id for s in project.segments if s.id in todo and s.etat_ia == "echec"])
    project.preparation.update(etat="terminee", terminee_le=now_iso())
    return save_project(project, project_file)


def prepare(video: Path, intention: Path, *, sous_titres: Path | None = None,
            langue: str | None = None, fournisseur: str = "mock", modele: str | None = None,
            url: str | None = None, sortie: Path | None = None, images_par_passage: int = 2,
            images_contexte: int = 2, secondes_contexte: float = 3.0,
            choix_images: str = "auto", seconde_lecture: bool | str = False,
            modele_seconde_lecture: str | None = None,
            max_revisions: int = 2, pause_min: float = 1.6, passage_max: float = 8.0,
            marge: float = 0.3, mots_max: int = 30, remplacer: bool = False,
            reprendre: bool = False, refaire_echecs: bool = False,
            log: Callable[[str], None] = print) -> Path:
    """Find the pauses, extract frames, let the agent draft every description.

    images_contexte frames come from the secondes_contexte seconds before each pause, so the
    model sees reactions and changes (a smile that fades), not one still moment; 0 turns
    them off. choix_images « auto » takes, in each group, the moments where the image changes
    most (« fixe »: evenly spaced, as before). seconde_lecture: the visual claims are checked
    on the same images once more (one more call per passage that describes people), by the
    same model (True or « meme ») or by another provider's (its name), which is less likely to
    make the same mistake.
    An existing project in the output folder is never overwritten: Wasf refuses,
    or with remplacer=True moves it to a dated backup folder first.

    The project is saved as soon as the pauses and their frames are ready, then after every
    passage. reprendre: go on with an interrupted run in the same folder, without asking the AI
    again for the passages already written. refaire_echecs: redo only the passages where the
    AI failed, unless someone has written them by hand since."""
    media.require_ffmpeg()
    video = Path(video).resolve()
    if not video.exists():
        raise FileNotFoundError(f"Vidéo introuvable : {video}")
    intent = load_intent(intention)
    intent.check_rights()
    if remplacer and (reprendre or refaire_echecs):
        raise ResumeError("--remplacer repart de zéro, alors que --reprendre et --refaire-echecs "
                          "gardent le projet : choisissez l'un ou l'autre.")
    chosen = langue or intent.langue          # the director's choice: --langue, then the intent
    provider = get_provider(fournisseur, modele, url)  # fail fast if the key is missing
    checker, second_label = _second_reader(seconde_lecture, modele_seconde_lecture, provider)
    for model in (provider, checker):
        if model is not None:  # « waiting for the rate limit » shows up with the rest of the log
            model.notify = log
    if provider.name == "mock":
        log("Fournisseur « mock » : simulation hors ligne, aucune image ne sera analysée. "
            "Les exports l'annonceront comme une simulation.")
    if provider.name in ("gemini", "anthropic", "openai") and not url:
        log(f"Rappel données : les images extraites et le texte partent chez « {provider.name} ». "
            "Une offre gratuite peut les réutiliser (c'est le cas chez Gemini) : pour un film réel, "
            "prenez une offre payante qui l'exclut, ou --fournisseur ollama.")

    total = media.duration(video)
    try:
        frame_rate = media.video_size(video)[2]
    except media.MediaError:
        frame_rate = None
    cues, encoding = [], ""
    if sous_titres:
        # Never read with replacement characters: Arabic subtitles made on Windows are often in
        # Windows-1256. The encoding found is logged and kept in the project.
        cues, encoding, warnings = load_subtitles(sous_titres)
        log(f"Sous-titres : {len(cues)} réplique(s), encodage {ENCODING_NAMES[encoding]}.")
        for warning in warnings:
            log(f"Attention : {warning}")
    out_dir = (Path(sortie) if sortie else video.parent / f"{video.stem}_wasf").resolve()
    if reprendre or refaire_echecs:
        return _go_on(out_dir, video, provider, checker, second_label, chosen, cues,
                      reprendre=reprendre, refaire_echecs=refaire_echecs, sous_titres=sous_titres,
                      max_revisions=max_revisions, log=log)
    # Nobody chose: the track speaks the film's language (a French film gets a French track
    # and a French voice). A choice that differs from the dialogue is kept, with a warning.
    spoken = dialogue_language(" ".join(cue.text for cue in cues))
    langue = chosen or spoken or "fr"
    log(_language_note(langue, chosen, spoken))
    windows = plan_windows(total, cues=cues, video=video, min_gap=pause_min, max_len=passage_max)
    rate = intent.mots_par_seconde or WORDS_PER_SECOND[langue]
    _protect_existing(out_dir, remplacer, log)
    (out_dir / "images").mkdir(parents=True, exist_ok=True)

    context = max(0, images_contexte) if secondes_contexte > 0 else 0
    segments: list[Segment] = []
    for window in windows:
        start, end = window.start + marge, window.end - marge
        # Round before truncating: 25.7 - 21.3 is 4.3999... in floating point, which cost a word.
        budget = min(mots_max, int(round((end - start) * rate, 6)))
        if budget < 3:
            continue
        before, after = neighbours(cues, window)
        notes = intent.notes_for(window.start, window.end)
        seg = Segment(id=f"p{len(segments) + 1:03d}", debut=round(window.start, 3),
                      fin=round(window.end, 3), parole_debut=round(start, 3),
                      parole_fin=round(end, 3), budget_mots=budget, source=window.source,
                      dialogue_avant=before, dialogue_apres=after,
                      a_remarquer=notes["a_remarquer"], a_eviter=notes["a_eviter"],
                      contexte=notes["contexte"])
        frames: list[tuple[float, str, int]] = []   # (time, file name, width), in film order
        adaptive = choix_images != "fixe"
        if context:
            even = [t for t in (window.start - secondes_contexte * (context - k) / context
                                for k in range(context)) if 0.0 <= t < total - 0.1]
            lo, hi = max(0.0, window.start - secondes_contexte), min(window.start, total - 0.1)
            times = (_moments(video, lo, hi, context, even, adaptive, frame_rate)
                     if hi > lo else even)
            frames += [(t, f"{seg.id}_avant{k + 1}.jpg", CONTEXT_FRAME_WIDTH)
                       for k, t in enumerate(times)]
        count = max(1, images_par_passage)
        even = [min(window.start + (k + 1) * window.duration / (count + 1), max(0.0, total - 0.1))
                for k in range(count)]
        times = _moments(video, window.start, min(window.end, total - 0.1), count, even,
                         adaptive, frame_rate)
        frames += [(t, f"{seg.id}_{k + 1}.jpg", 768) for k, t in enumerate(times)]
        for t, name, width in frames:
            media.extract_frame(video, t, out_dir / "images" / name, max_width=width)
            seg.images.append(f"images/{name}")
            seg.instants.append(round(t, 3))
        seg.etat_ia = "a_faire"
        segments.append(seg)

    source = "sous-titres" if cues else "détection des silences"
    log(f"{len(segments)} pause(s) exploitable(s) trouvée(s) ({source}).")
    project = Project(film=intent.film, video=_relative(video, out_dir), duree=round(total, 3),
                      langue=langue, fournisseur=provider.name, modele=provider.model,
                      realisateur=intent.realisateur, descripteur=intent.descripteur,
                      accord_producteur=intent.accord_producteur,
                      reference_accord=intent.reference_accord,
                      intention_globale=intent.intention_globale, style=intent.style,
                      personnages=intent.personnages, lexique=intent.lexique,
                      exemples=intent.exemples, emotions=intent.emotions, segments=segments,
                      mots_par_seconde=rate, encodage_sous_titres=encoding,
                      empreinte_film=media.fingerprint(video),
                      cree_le=now_iso(), wasf_version=__version__)
    project.seconde_lecture = second_label
    project.preparation = {"etat": "en_cours", "commencee_le": now_iso()}
    project_file = out_dir / "projet.json"
    save_project(project, project_file)        # the plan and its frames, before any AI call
    agent = DescriberAgent(provider, film=intent.film, langue=langue,
                           intention_globale=intent.intention_globale, style=intent.style,
                           personnages=intent.personnages, lexique=intent.lexique,
                           exemples=intent.exemples, max_revisions=max_revisions,
                           emotions_mode=intent.emotions, second_look=checker is not None,
                           checker=checker, log=log)
    project.energie["preparation"] = _draft(project, project_file, [s.id for s in segments],
                                            agent, cues, provider, checker, log)
    project.echantillon = draw_sample(segments)
    project.modeles_utilises = _models(project, provider, checker)
    project.log("preparation", fournisseur=provider.name, modele=provider.model,
                passages=len(segments), exemples=len(intent.exemples),
                images_par_passage=max(1, images_par_passage), images_contexte=context,
                choix_images="fixe" if choix_images == "fixe" else "auto",
                seconde_lecture=second_label,
                emotions=intent.emotions, echantillon=project.echantillon)
    project.preparation.update(etat="terminee", terminee_le=now_iso())
    return save_project(project, project_file)


@dataclass
class RenderOptions:
    moteur: str = "espeak"
    voix: str | None = None
    enregistrements: Path | None = None
    attenuation_db: float = -12.0
    tempo_max: float = 1.3
    brouillon: bool = False
    annonce: bool = True
    sans_validation_realisateur: bool = False
    sortie: Path | None = None
    couper_silences: bool = False
    # Engine « humain »: what the team declares about its recordings (tts.declared_source).
    source_voix: str | None = None   # humaine | synthese | inconnue
    voix_de: str | None = None       # who lent their voice, or which tool made it


def readiness_problems(project: Project, opts: RenderOptions) -> list[str]:
    """Human control: nothing is published without a signature and the director's approval."""
    problems = []
    if not project.signataire:
        problems.append("personne n'a signé : indiquez la réalisation (ou l'audiodescripteur·rice) "
                        "dans l'éditeur de relecture")
    pending = [s.id for s in project.segments if s.statut not in ("valide", "ignore")]
    if pending:
        shown = ", ".join(pending[:8]) + ("…" if len(pending) > 8 else "")
        problems.append(f"{len(pending)} passage(s) non validé(s) : {shown}")
    if not project.validation_realisateur and not opts.sans_validation_realisateur:
        problems.append("la réalisation n'a pas approuvé la piste "
                        "(case dans l'éditeur, ou option --sans-validation-realisateur)")
    return problems


# Why a final export stops on a voice, and what to do about it, by kind of problem.
REFUSALS = {
    "deborde": {"titre": "une voix ne tient pas dans sa pause ou chevauche la suivante",
                "raison": "voix hors de sa pause",
                "conseil": "raccourcissez ces passages dans l'éditeur (wasf relire {projet}), "
                           "où leur durée mesurée est affichée"},
    "muette": {"titre": "une voix est muette ou presque", "raison": "voix muette",
               "conseil": "refaites les voix muettes (fichier vide, micro coupé ?)"},
}
REFUSALS["chevauche"] = REFUSALS["deborde"]
REFUSALS["hors_film"] = {"titre": "un passage tombe après la fin du film",
                         "raison": "passage hors du film",
                         "conseil": "vérifiez que la vidéo est bien celle de la préparation"}
REFUSALS["coupee"] = {**REFUSALS["hors_film"], "titre": "la fin du film couperait une voix"}
FILM_LENGTH_TOLERANCE = 0.5   # seconds between the video's length now and at preparation


def _film_check(project: Project, video: Path) -> dict:
    """Is the video the same file as at preparation? Compared by fingerprint, since a new edit
    of the same length passes the length check. A warning, not a refusal: a re-encoded copy of
    the same edit (lighter, other format) changes the fingerprint too, and is fine."""
    now = media.fingerprint(video)
    if not project.empreinte_film:
        return {"identique": None, "empreinte_preparation": None, "empreinte_export": now,
                "remarque": "projet préparé sans empreinte du film : seule la durée a été "
                            "comparée"}
    same = now == project.empreinte_film
    return {"identique": same, "empreinte_preparation": project.empreinte_film,
            "empreinte_export": now,
            "remarque": ("même fichier qu'à la préparation" if same else
                         "le fichier a changé depuis la préparation, à durée égale : autre "
                         "montage ou simple réencodage, à vérifier avant de diffuser")}


def _refusal_parts(problems: list[dict], key: str, **values) -> list[str]:
    parts: list[str] = []
    for problem in problems:
        text = REFUSALS[problem["code"]][key].format(**values)
        if text not in parts:
            parts.append(text)
    return parts


def _refusal_message(problems: list[dict], project_path: Path) -> str:
    """The final export's refusal: what is wrong, passage by passage, and what to do."""
    advice = " ; ".join(_refusal_parts(problems, "conseil", projet=project_path))
    return ("Export refusé : " + " ; ".join(_refusal_parts(problems, "titre")) + ".\n- "
            + "\n- ".join(p["message"] for p in problems)
            + f"\n{advice[0].upper()}{advice[1:]}, ou faites une version de travail avec "
              "--brouillon.")


IGNORED_FILES = {"desktop.ini", "thumbs.db", ".ds_store"}


def check_recordings(folder: Path | None, needed: list[str], known: list[str],
                     announce: str | None, log: Callable[[str], None] = print) -> None:
    """Human voice: look at every recording before any work starts, and name everything that is
    missing or unreadable at once (the export used to stop at the first, one run at a time).

    `needed`: the passages this export speaks; `known`: every passage of the project, so that a
    file is called misnamed only when it belongs to none; `announce`: the sentence of the opening
    card, or None without the card. A missing or unreadable announcement only leaves the card
    silent, as before: it is a warning that says which sentence to record."""
    if not folder:
        raise RenderError("Moteur « humain » : indiquez le dossier des enregistrements avec "
                          "--enregistrements.")
    folder = Path(folder)
    if not folder.is_dir():
        raise RenderError(f"Dossier des enregistrements introuvable : {folder}")
    missing, unreadable = [], []
    for seg_id in needed:
        found = find_recording(folder, seg_id)
        if found is None:
            missing.append(seg_id)
        elif problem := media.audio_problem(found):
            unreadable.append(f"{found.name} ({problem})")
    if announce is not None:
        found = find_recording(folder, "annonce")
        problem = "absent" if found is None else media.audio_problem(found)
        if problem:
            name = "annonce.wav" if found is None else found.name
            log(f"Attention : {name} {problem} dans {folder} : le carton d'annonce en tête du "
                f"film restera muet. Phrase à enregistrer : « {announce} »")
    if not missing and not unreadable:
        return
    lines = [f"Enregistrements à compléter avant l'export, dans {folder} :"]
    if missing:
        lines.append(f"- manquants ({len(missing)}) : {', '.join(missing)}")
    if unreadable:
        lines.append(f"- inutilisables ({len(unreadable)}) : {', '.join(unreadable)}")
    lines.append("Chaque passage attend un fichier à son nom, par exemple "
                 f"{(missing or needed)[0]}.wav, ou .mp3, .m4a, .ogg, .flac, .opus.")
    names = {seg_id.lower() for seg_id in known} | {"annonce"}
    others = sorted(p.name for p in folder.iterdir()
                    if p.is_file() and not p.name.startswith(".")
                    and p.name.lower() not in IGNORED_FILES
                    and (p.stem.lower() not in names
                         or p.suffix.lower() not in RECORDING_EXTENSIONS))
    if others:
        shown = ", ".join(others[:8]) + ("…" if len(others) > 8 else "")
        lines.append(f"Fichiers du dossier qui ne servent à aucun passage (nom ou format) : {shown}")
    raise RenderError("\n".join(lines))


VOICE_FIELDS = ("duree_source_s", "duree_voix_s", "acceleration", "duree_disponible_s",
                "depassement_s", "deborde", "chevauche", "alertes")


def _record_voices(project: Project, placed: list[dict], texts: dict[str, str],
                   opts: RenderOptions) -> None:
    """Keep each voice's measured length on its passage, with the text it was measured for:
    the review editor shows it, and warns while that text has not been shortened."""
    when = now_iso()
    measured = {p["id"]: p for p in placed}
    for seg in project.segments:
        voice = measured.get(seg.id)
        if voice is None:
            continue
        seg.voix_mesuree = {"texte": texts.get(seg.id, seg.texte), "moteur": opts.moteur,
                            "voix": opts.voix or "", "quand": when, "brouillon": opts.brouillon,
                            **{key: voice.get(key) for key in VOICE_FIELDS}}
        refresh_voice_check(seg)


def render(project_path: Path, opts: RenderOptions,
           log: Callable[[str], None] = print) -> dict[str, Path]:
    media.require_ffmpeg()
    if (opts.source_voix or opts.voix_de) and opts.moteur != "humain":
        raise RenderError("--source-voix et --voix-de décrivent des enregistrements fournis par "
                          "l'équipe : ils ne servent qu'avec --voix-moteur humain. Avec une voix "
                          "de synthèse, Wasf sait déjà laquelle et la nomme lui-même.")
    if opts.voix_de and not opts.source_voix:
        raise RenderError("--voix-de demande aussi --source-voix (humaine, synthese ou "
                          "inconnue) : dites d'abord ce que sont ces enregistrements.")
    project_path = Path(project_path).resolve()
    project = load_project(project_path)
    base = project_path.parent
    video = (base / project.video).resolve()
    if not video.exists():
        raise RenderError(f"Vidéo introuvable : {video}")
    if project.duree:          # the same film as at preparation, or the passages fall elsewhere
        length = media.duration(video)
        if abs(length - project.duree) > FILM_LENGTH_TOLERANCE:
            now, then = (f"{x:.1f}".replace(".", ",") for x in (length, project.duree))
            what = (f"la vidéo {video.name} dure {now} s, mais la piste a été préparée sur une "
                    f"vidéo de {then} s : les descriptions tomberaient au mauvais endroit, et "
                    "celles d'après la fin seraient perdues.")
            if not opts.brouillon:
                raise RenderError(
                    "Export refusé : la vidéo a changé depuis la préparation ; " + what
                    + "\nRemettez la vidéo d'origine, refaites la préparation sur celle-ci "
                      "(wasf preparer … --remplacer), ou faites une version de travail avec "
                      "--brouillon.")
            log("Attention : " + what + " Version de travail faite quand même.")
    if project.preparation_en_cours:
        left = sum(s.etat_ia == "a_faire" for s in project.segments)
        raise RenderError(f"La préparation de ce projet n'est pas terminée ({left} passage(s) "
                          "sans brouillon) : continuez-la avec « wasf preparer … --reprendre », "
                          "puis relisez la piste.")

    problems = readiness_problems(project, opts)
    if problems and not opts.brouillon:
        raise RenderError("Export refusé :\n- " + "\n- ".join(problems)
                          + "\nTerminez la relecture, ou utilisez --brouillon pour une version de travail.")
    out = (Path(opts.sortie) if opts.sortie else base / "export").resolve()
    chosen = [s for s in project.segments
              if s.statut != "ignore" and s.texte.strip() and (opts.brouillon or s.statut == "valide")]
    if not chosen:
        raise RenderError("Aucun passage à vocaliser.")
    film_check = _film_check(project, video)
    if film_check["identique"] is False:
        log("Attention : le fichier de la vidéo n'est plus le même qu'à la préparation, à durée "
            "égale. Si le montage a changé, des descriptions peuvent tomber au mauvais endroit : "
            "vérifiez-les avant de diffuser. (Une copie réencodée du même montage donne aussi ce "
            "message.)")
    if opts.moteur == "humain":    # every recording is looked at before any work starts
        check_recordings(opts.enregistrements, [s.id for s in chosen],
                         [s.id for s in project.segments],
                         label_text(project, opts.brouillon) if opts.annonce else None, log)
    out.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, Path] = {}
    texts = {s.id: s.texte for s in chosen}
    with EnergyMeter("export") as meter:
        try:
            # Final export: a voice that overruns its pause (so talks over the actors) or runs
            # into the next one stops everything before the mix. A working version goes on.
            mix = build_mix(video, chosen, out, langue=project.langue, moteur=opts.moteur,
                            voix=opts.voix, enregistrements=opts.enregistrements,
                            duree=project.duree, attenuation_db=opts.attenuation_db,
                            tempo_max=opts.tempo_max, log=log, strict=not opts.brouillon,
                            couper_silences=opts.couper_silences,
                            mots_par_seconde=project.mots_par_seconde or None)
        except VoiceTimingError as exc:
            # The editor may have saved since the start: reload, change only the measurements.
            fresh = load_project(project_path)
            _record_voices(fresh, exc.placed, texts, opts)
            fresh.log("export_refuse", raison=" ; ".join(_refusal_parts(exc.problems, "raison")),
                      passages=sorted({p["id"] for p in exc.problems}))
            save_project(fresh, project_path)
            raise RenderError(_refusal_message(exc.problems, project_path)) from None
        _record_voices(project, mix["passages"], texts, opts)
        outputs["piste_audiodecrite"] = mix["piste_mixee"]
        outputs["voix_seule"] = mix["voix_seule"]
        final = out / "film_audiodecrit.mp4"
        if not opts.annonce:
            outputs["film"] = media.mux(video, mix["piste_mixee"], final,
                                        LANG3.get(project.langue, "fra"))
        else:
            tracks = media.mux(video, mix["piste_mixee"], out / "film_pistes.tmp.mp4",
                               LANG3.get(project.langue, "fra"))
            announce = out / "annonce.wav"
            try:
                synthesize(opts.moteur, label_text(project, opts.brouillon), announce,
                           langue=project.langue, voix=opts.voix, segment_id="annonce",
                           enregistrements=opts.enregistrements)
            except (TTSError, media.MediaError) as exc:   # an unreadable recording included
                log(f"Annonce non vocalisée ({exc}) : le carton reste muet.")
                media.write_wav(announce, np.zeros(48000, dtype=np.float32))
            seconds = max(4.0, media.duration(announce) + 1.0)
            width, height, _ = media.video_size(video)
            card = make_card(project, out / "carton_annonce.png", width, height, opts.brouillon)
            outputs["film"] = media.prepend_card(tracks, announce, final, seconds, card)
            tracks.unlink(missing_ok=True)

    label = label_text(project, opts.brouillon)
    outputs["sous_titres_vtt"] = write_vtt(chosen, out / "audiodescription.vtt", label)
    outputs["sous_titres_srt"] = write_srt(chosen, out / "audiodescription.srt", label,
                                           notice_seconds(label, project.langue,
                                                          project.mots_par_seconde or None))
    project.energie["export"] = meter.result
    voice = {**describe_voice(opts.moteur, opts.voix, project.langue, opts.source_voix,
                              opts.voix_de),
             "silences_coupes": opts.couper_silences}
    report = transparency_report(project, mix["passages"], opts.brouillon, voix=voice,
                                 controles=mix["problemes"] + mix["controles"],
                                 controle_film=film_check)
    outputs["rapport"] = write_report(report, out / "rapport_transparence.json")
    outputs["credits"] = write_credits(report, out / "credits.txt")
    # The editor may have saved while the film was being made: never write back the copy read
    # at the start. Reload, add only this export's measurements and log line, and say what the
    # film does not contain.
    fresh = load_project(project_path)
    changed = changed_during_export(project, fresh, opts.brouillon)
    _record_voices(fresh, mix["passages"], texts, opts)
    fresh.energie["export"] = meter.result
    entry = {"moteur": opts.moteur, "brouillon": opts.brouillon, "passages": len(chosen)}
    if opts.moteur == "humain":    # the team's word about its recordings, as said
        entry["source_voix_declaree"] = opts.source_voix or "non_declaree"
    if film_check["identique"] is False:
        entry["film_modifie_depuis_preparation"] = True
    if changed:
        entry["modifie_pendant_export"] = changed
        log("Attention : la piste a été modifiée pendant l'export (" + " ; ".join(changed)
            + "). Ces changements sont bien enregistrés, mais ce film ne les contient pas : "
              "relancez « wasf exporter » pour les y mettre.")
    fresh.log("export", **entry)
    save_project(fresh, project_path)
    return outputs


def changed_during_export(before: Project, after: Project, brouillon: bool = False) -> list[str]:
    """What the review changed between the start of an export and its end: the film was made
    from `before`, so these changes are not in it."""
    changes = []
    old = {seg.id: seg for seg in before.segments}
    for seg in after.segments:
        was = old.pop(seg.id, None)
        if was is None:
            changes.append(f"{seg.id} : passage ajouté")
        elif seg.texte != was.texte:
            changes.append(f"{seg.id} : texte modifié")
        elif seg.statut != was.statut:
            changes.append(f"{seg.id} : {was.statut} → {seg.statut}")
    changes += [f"{seg_id} : passage retiré" for seg_id in old]
    if after.validation_realisateur != before.validation_realisateur:
        changes.append("approbation de la réalisation "
                       + ("donnée" if after.validation_realisateur else "retirée"))
    elif label_text(after, brouillon) != label_text(before, brouillon):
        changes.append("signatures (la mention lue en tête du film change)")
    return changes

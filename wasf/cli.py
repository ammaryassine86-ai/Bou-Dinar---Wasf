"""Command line: wasf demo | preparer | relire | exporter."""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__
from .gaps import SubtitleError
from .intent import LANGUAGES, IntentError, RightsError
from .media import MediaError
from .pipeline import (
    ProjectExistsError,
    RenderError,
    RenderOptions,
    ResumeError,
    prepare,
    render,
)
from .project import ProjectFileError
from .providers import PROVIDERS, ProviderError
from .tts import ENGINES, VOICE_SOURCES, TTSError

KNOWN_ERRORS = (MediaError, IntentError, RightsError, ProviderError, TTSError, RenderError,
                ProjectExistsError, FileNotFoundError, SubtitleError, ResumeError,
                ProjectFileError)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wasf",
        description="Wasf — audiodescription assistée par IA, écrite et validée par des humains.")
    parser.add_argument("--version", action="version", version=f"wasf {__version__}")
    sub = parser.add_subparsers(dest="commande", required=True)

    d = sub.add_parser("demo", help="Crée un clip de démonstration pour tester Wasf sans film.")
    d.add_argument("dossier", type=Path, nargs="?", default=Path("demo"))
    d.add_argument("--langue", "--lang", choices=sorted(LANGUAGES), default="fr")

    p = sub.add_parser("preparer", aliases=["prepare"],
                       help="Trouve les pauses et fait écrire la piste par l'agent.")
    p.add_argument("video", type=Path)
    p.add_argument("--intention", "--intent", type=Path, required=True,
                   help="Fichier YAML d'intention de la réalisation (voir examples/).")
    p.add_argument("--sous-titres", "--subtitles", dest="sous_titres", type=Path,
                   help="Sous-titres SRT ou WebVTT (recommandé : pauses plus fiables).")
    p.add_argument("--langue", "--lang", choices=sorted(LANGUAGES),
                   help="fr, ar (arabe standard) ou aeb (derja). Par défaut : celle de "
                        "l'intention, sinon celle des dialogues (sous-titres).")
    p.add_argument("--fournisseur", "--provider", choices=PROVIDERS, required=True,
                   help="Modèle d'IA : gemini, anthropic, openai, ollama, ou mock "
                        "(simulation hors ligne, annoncée comme telle).")
    p.add_argument("--modele", "--model", help="Nom du modèle chez le fournisseur.")
    p.add_argument("--url", help="URL de base de l'API (serveur local, Ollama distant…).")
    p.add_argument("--sortie", "--out", type=Path, help="Dossier du projet (défaut : <vidéo>_wasf).")
    p.add_argument("--remplacer", "--replace", action="store_true",
                   help="Remplace un projet existant ; l'ancien est gardé dans « sauvegarde-… ».")
    p.add_argument("--reprendre", "--resume", action="store_true",
                   help="Continue une préparation interrompue dans le même dossier : les "
                        "passages déjà écrits ne sont pas redemandés à l'IA.")
    p.add_argument("--refaire-echecs", "--retry-failed", dest="refaire_echecs", action="store_true",
                   help="Refait seulement les passages où l'IA a échoué (erreur, quota…), sauf "
                        "ceux écrits à la main depuis ; les autres restent tels quels.")
    p.add_argument("--images", type=int, default=2,
                   help="Images prises pendant chaque pause (défaut : 2).")
    p.add_argument("--images-contexte", type=int, default=2,
                   help="Images prises juste avant chaque pause, pendant le dialogue, pour saisir "
                        "réactions et changements d'expression (défaut : 2 ; 0 pour aucune).")
    p.add_argument("--secondes-contexte", type=float, default=3.0,
                   help="Durée avant la pause où prendre ces images (défaut : 3 s).")
    p.add_argument("--choix-images", choices=["auto", "fixe"], default="auto",
                   help="auto : garder les moments où l'image change le plus (défaut) ; "
                        "fixe : images régulièrement espacées.")
    p.add_argument("--seconde-lecture", nargs="?", const="meme", default=None,
                   choices=["meme", "gemini", "anthropic", "openai", "ollama"],
                   metavar="FOURNISSEUR",
                   help="Les affirmations visuelles sont revérifiées sur les images : par le même "
                        "modèle, ou par un autre fournisseur (gemini, anthropic, openai, ollama), "
                        "qui risque moins de refaire la même erreur. Un appel de plus par passage "
                        "qui décrit des personnes.")
    p.add_argument("--modele-seconde-lecture", default=None,
                   help="Modèle de cet autre fournisseur (défaut : son modèle par défaut).")
    p.add_argument("--revisions", type=int, default=2, help="Révisions automatiques maximum.")
    p.add_argument("--pause-min", type=float, default=1.6, help="Pause minimale en secondes.")
    p.add_argument("--passage-max", type=float, default=8.0, help="Durée maximale d'un passage.")

    r = sub.add_parser("relire", aliases=["review"], help="Ouvre l'éditeur de relecture.")
    r.add_argument("projet", type=Path)
    r.add_argument("--port", type=int, default=8765)
    r.add_argument("--hote", "--host", default="127.0.0.1",
                   help="127.0.0.1 (défaut), localhost ou ::1 : l'éditeur n'est jamais ouvert "
                        "au réseau.")
    r.add_argument("--sans-navigateur", action="store_true")

    e = sub.add_parser("exporter", aliases=["render"],
                       help="Vocalise les descriptions validées et produit le film audiodécrit.")
    e.add_argument("projet", type=Path)
    e.add_argument("--voix-moteur", "--tts", dest="moteur", choices=ENGINES, default="espeak")
    e.add_argument("--voix", help="Voix (Azure : ar-TN-ReemNeural… ; Piper : chemin du .onnx).")
    e.add_argument("--enregistrements", type=Path,
                   help="Moteur « humain » : dossier contenant p001.wav, p002.wav… et annonce.wav.")
    e.add_argument("--attenuation", type=float, default=-12.0,
                   help="Baisse du son du film sous la voix, en dB (défaut : -12).")
    e.add_argument("--brouillon", action="store_true",
                   help="Version de travail : autorise les passages non validés (annoncée comme telle).")
    e.add_argument("--sans-annonce", action="store_true",
                   help="Pas de carton d'annonce IA en tête (la mention reste dans les fichiers).")
    e.add_argument("--sans-validation-realisateur", action="store_true")
    e.add_argument("--couper-silences", action="store_true",
                   help="Retire le silence avant et après chaque voix (jamais au milieu), "
                        "par exemple au début et à la fin d'enregistrements au téléphone.")
    e.add_argument("--source-voix", choices=tuple(VOICE_SOURCES),
                   help="Moteur « humain » : ce que sont les enregistrements, selon l'équipe "
                        "(humaine, synthese ou inconnue). Repris comme une déclaration : Wasf "
                        "ne peut pas le vérifier.")
    e.add_argument("--voix-de",
                   help="Avec --source-voix : qui a prêté sa voix (avec son accord), ou quel "
                        "outil a fait les voix.")
    e.add_argument("--sortie", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.commande == "demo":
            from .demo import make_demo
            files = make_demo(args.dossier, args.langue)
            print("Clip de démonstration créé :")
            for name, path in files.items():
                print(f"  {name:12s} {path}")
            print(f"\nÉtape suivante (simulation hors ligne, sans clé) :\n  wasf preparer "
                  f"{files['video']} --intention {files['intention']} --sous-titres "
                  f"{files['sous_titres']} --fournisseur mock")
        elif args.commande in ("preparer", "prepare"):
            path = prepare(args.video, args.intention, sous_titres=args.sous_titres,
                           langue=args.langue, fournisseur=args.fournisseur, modele=args.modele,
                           url=args.url, sortie=args.sortie, images_par_passage=args.images,
                           images_contexte=args.images_contexte,
                           secondes_contexte=args.secondes_contexte,
                           choix_images=args.choix_images, seconde_lecture=args.seconde_lecture,
                           modele_seconde_lecture=args.modele_seconde_lecture,
                           max_revisions=args.revisions, pause_min=args.pause_min,
                           passage_max=args.passage_max, remplacer=args.remplacer,
                           reprendre=args.reprendre, refaire_echecs=args.refaire_echecs)
            print(f"\nProjet créé : {path}\nÉtape suivante : wasf relire {path}")
        elif args.commande in ("relire", "review"):
            from .editor.app import EditorHostError, check_host, create_app, serve
            try:
                check_host(args.hote)       # this computer only, before anything starts
            except EditorHostError as exc:
                print(f"Erreur : {exc}", file=sys.stderr)
                return 1
            app = create_app(args.projet)
            shown = f"[{args.hote}]" if ":" in args.hote else args.hote
            url = f"http://{shown}:{args.port}/"
            print(f"Éditeur de relecture : {url}  (Ctrl+C pour arrêter)")
            if not args.sans_navigateur:
                threading.Timer(1.0, lambda: webbrowser.open(url)).start()
            serve(app, args.hote, args.port)
        elif args.commande in ("exporter", "render"):
            opts = RenderOptions(moteur=args.moteur, voix=args.voix,
                                 enregistrements=args.enregistrements,
                                 attenuation_db=args.attenuation, brouillon=args.brouillon,
                                 annonce=not args.sans_annonce,
                                 sans_validation_realisateur=args.sans_validation_realisateur,
                                 sortie=args.sortie,
                                 couper_silences=args.couper_silences,
                                 source_voix=args.source_voix, voix_de=args.voix_de)
            outputs = render(args.projet, opts)
            print("Fichiers produits :")
            for name, path in outputs.items():
                print(f"  {name:20s} {path}")
    except KNOWN_ERRORS as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # preparer has already said what is saved and how to go on (--reprendre).
        print("Arrêté (Ctrl+C).", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())

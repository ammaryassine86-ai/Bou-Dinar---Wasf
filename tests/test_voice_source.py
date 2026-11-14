"""Lot 3, point N: with the engine « humain », the team can declare what its recordings are
(human voices, synthetic voices made elsewhere, or unknown) and who lent their voice. Wasf
cannot check it: the report and the credits keep it as the team's declaration, marked as not
verified, and say so when nothing was declared.

Before: the report could only say « enregistrements fournis par l'équipe », even when the team
knew more, and nothing let it say that a supplied file was a synthetic voice."""
import json
from pathlib import Path

import numpy as np
import pytest

from wasf import media
from wasf.cli import main
from wasf.pipeline import RenderError, RenderOptions, render
from wasf.project import load_project, now_iso, save_project
from wasf.tts import TTSError, declared_source, describe_voice, estimated_seconds

RATE = 48000
DIRECTOR = "Réalisatrice A"


def _approve(path: Path) -> list:
    project = load_project(path)
    project.realisateur = DIRECTOR
    for seg in project.segments:
        seg.statut, seg.valide_par, seg.valide_le = "valide", DIRECTOR, now_iso()
    project.validation_realisateur, project.approuve_par = True, DIRECTOR
    save_project(project, path)
    return project.segments


def _recordings(folder: Path, segments: list) -> Path:
    """A clean stand-in recording per passage, shorter than its pause."""
    for seg in segments:
        seconds = min(0.9 * seg.duree_parole, max(0.6, estimated_seconds(seg.texte, "fr")))
        t = np.arange(int(seconds * RATE)) / RATE
        fade = np.minimum(1.0, np.minimum(t, seconds - t) / 0.03)
        voice = 0.3 * np.sin(2 * np.pi * 220 * t) * (0.55 + 0.45 * np.abs(np.sin(4 * np.pi * t)))
        media.write_wav(folder / f"{seg.id}.wav", (voice * fade).astype(np.float32), RATE)
    return folder


def test_nothing_declared_is_said_as_such():
    voice = describe_voice("humain", None, "aeb")
    assert voice["declaration"] == {"source": "non_declaree", "par": None,
                                    "verifiee_par_wasf": False,
                                    "remarque": "l'équipe n'a pas déclaré l'origine des "
                                                "enregistrements"}


def test_a_declaration_is_kept_as_said_and_never_verified():
    voice = describe_voice("humain", None, "aeb", "humaine", "  Riadh  ")
    assert voice["declaration"]["source"] == "humaine"
    assert voice["declaration"]["par"] == "Riadh"
    assert voice["declaration"]["verifiee_par_wasf"] is False
    assert "non vérifiée" in voice["declaration"]["remarque"]
    assert declared_source("synthese", "outil X")["source"] == "synthese"
    with pytest.raises(TTSError):
        declared_source("robot", None)


def test_synthetic_engines_need_no_declaration():
    """Wasf made those voices itself: it names them, nothing to declare."""
    assert "declaration" not in describe_voice("azure", None, "aeb")
    assert "declaration" not in describe_voice("espeak", None, "fr")


def test_a_declaration_with_a_synthetic_engine_is_refused(real_path):
    with pytest.raises(RenderError, match="--voix-moteur humain"):
        render(real_path, RenderOptions(moteur="bip", source_voix="humaine"), log=lambda _m: None)


def test_a_name_without_a_source_is_refused(real_path, tmp_path):
    with pytest.raises(RenderError, match="--source-voix"):
        render(real_path, RenderOptions(moteur="humain", enregistrements=tmp_path, voix_de="Riadh"),
               log=lambda _m: None)


def test_the_report_and_the_credits_say_who_declared_what(real_path, tmp_path):
    segments = _approve(real_path)
    folder = _recordings(tmp_path / "voix", segments)
    outputs = render(real_path, RenderOptions(moteur="humain", enregistrements=folder,
                                              annonce=False, source_voix="humaine",
                                              voix_de="Riadh"), log=lambda _m: None)
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    declaration = report["voix_utilisee"]["declaration"]
    assert declaration["source"] == "humaine" and declaration["par"] == "Riadh"
    assert declaration["verifiee_par_wasf"] is False
    credits = outputs["credits"].read_text(encoding="utf-8")
    assert ("déclarés comme voix humaines (Riadh), déclaration non vérifiée par Wasf"
            in credits)
    assert load_project(real_path).historique[-1]["source_voix_declaree"] == "humaine"


def test_without_a_declaration_the_credits_say_none_was_made(real_path, tmp_path):
    segments = _approve(real_path)
    folder = _recordings(tmp_path / "voix", segments)
    outputs = render(real_path, RenderOptions(moteur="humain", enregistrements=folder,
                                              annonce=False), log=lambda _m: None)
    assert "origine non déclarée par l'équipe" in outputs["credits"].read_text(encoding="utf-8")


def test_the_command_line_refuses_a_declaration_for_a_synthetic_voice(real_path, capsys):
    code = main(["exporter", str(real_path), "--voix-moteur", "espeak",
                 "--source-voix", "humaine"])
    assert code == 1
    assert "--voix-moteur humain" in capsys.readouterr().err

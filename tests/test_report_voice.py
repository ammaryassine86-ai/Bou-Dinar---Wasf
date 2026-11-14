"""Lot 2, fix 5: the transparency report and the credits say who speaks the descriptions (a
person, a synthetic voice and which one, or a test signal) and what the voice checks found.

Before, neither rapport_transparence.json nor credits.txt said whether the voice was human or
synthetic. The checks are reported honestly: which ones ran, what they found, never « no
error » when warnings remain, and nothing at all when nothing was measured."""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from wasf import media
from wasf.export import transparency_report
from wasf.pipeline import RenderOptions, render
from wasf.project import load_project, now_iso, save_project
from wasf.tts import describe_voice, estimated_seconds

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


def _speech(seconds: float, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    syllables = 0.55 + 0.45 * np.abs(np.sin(np.pi * 4.0 * t))
    fade = np.minimum(1.0, np.minimum(t, seconds - t) / 0.03)
    return (amplitude * np.sin(2 * np.pi * 220 * t) * syllables * fade).astype(np.float32)


def _recordings(folder: Path, segments: list, amplitudes: dict | None = None) -> Path:
    for seg in segments:
        seconds = min(0.9 * seg.duree_parole, max(0.6, estimated_seconds(seg.texte, "fr")))
        level = (amplitudes or {}).get(seg.id, 0.3)
        samples = np.zeros(int(0.8 * RATE), np.float32) if level == 0 else _speech(seconds, level)
        media.write_wav(folder / f"{seg.id}.wav", samples, RATE)
    return folder


def _outputs(outputs: dict) -> tuple[dict, str]:
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    return report, outputs["credits"].read_text(encoding="utf-8")


def test_recordings_are_said_to_be_the_teams_own(real_path, tmp_path):
    """Wasf cannot hear whether a recording is a person: it says the team supplied the files
    and that it synthesised nothing, never more."""
    segments = _approve(real_path)
    folder = _recordings(tmp_path / "voix", segments)
    report, credits = _outputs(render(real_path, RenderOptions(
        moteur="humain", enregistrements=folder, annonce=False), log=lambda _m: None))
    assert report["voix_utilisee"]["type"] == "enregistrements_fournis"
    assert report["voix_utilisee"]["silences_coupes"] is False
    assert ("Voix : enregistrements fournis par l'équipe (moteur « humain »), sans synthèse "
            "vocale par Wasf") in credits
    assert "personne" not in credits.split("Voix :")[1].splitlines()[0]
    assert str(folder) not in json.dumps(report, ensure_ascii=False)     # no local path
    assert report["duree_film_s"] == load_project(real_path).duree
    audio = report["controle_audio"]
    assert audio["bloquants"] == 0 and audio["alertes"] == 0 and audio["problemes"] == []
    assert audio["resultat"] == "aucun problème trouvé par ces contrôles"
    assert "voix muette" in audio["controles_faits"]
    assert "Contrôle audio : aucun problème trouvé par ces contrôles" in credits


@pytest.mark.skipif(shutil.which("espeak-ng") is None and shutil.which("espeak") is None,
                    reason="espeak-ng n'est pas installé")
def test_a_synthetic_voice_is_named(real_path):
    _approve(real_path)
    report, credits = _outputs(render(real_path, RenderOptions(moteur="espeak", annonce=False),
                                      log=lambda _m: None))
    voice = report["voix_utilisee"]
    assert voice["type"] == "voix_de_synthese" and voice["service"] == "espeak-ng"
    assert voice["voix"] == "fr" and voice["sur_cet_ordinateur"] is True
    assert "Voix : voix de synthèse espeak-ng (fr), sur cet ordinateur" in credits


def test_a_test_signal_is_not_called_a_voice(real_path):
    _approve(real_path)
    report, credits = _outputs(render(real_path, RenderOptions(
        moteur="bip", annonce=False, couper_silences=True), log=lambda _m: None))
    assert report["voix_utilisee"]["type"] == "signal_de_test"
    assert "Voix : signal de test, pas une voix (essai technique) ; silence coupé" in credits


def test_every_engine_is_described_without_a_path():
    assert describe_voice("azure", None, "aeb")["voix"] == "ar-TN-ReemNeural"
    assert describe_voice("azure", None, "fr")["voix"] == "fr-FR-DeniseNeural"
    hedi = describe_voice("azure", "ar-TN-HediNeural", "aeb")
    assert hedi["libelle"] == "voix de synthèse ar-TN-HediNeural (Azure AI Speech)"
    assert hedi["sur_cet_ordinateur"] is False
    piper = describe_voice("piper", "/home/someone/voix/ar_JO-kareem-medium.onnx", "ar")
    assert piper["voix"] == "ar_JO-kareem-medium.onnx" and "/home" not in json.dumps(piper)
    assert describe_voice("espeak", None, "aeb")["voix"] == "ar"


def test_warnings_are_counted_and_never_called_no_error(real_path, tmp_path):
    segments = _approve(real_path)
    quiet = segments[1]
    folder = _recordings(tmp_path / "voix", segments, {quiet.id: 0.03})
    report, credits = _outputs(render(real_path, RenderOptions(
        moteur="humain", enregistrements=folder, annonce=False), log=lambda _m: None))
    audio = report["controle_audio"]
    assert audio["bloquants"] == 0 and audio["alertes"] == 1
    assert audio["par_type"] == {"volume": 1}
    problem = audio["problemes"][0]
    assert problem["id"] == quiet.id and problem["gravite"] == "alerte"
    assert problem["debut_s"] == quiet.parole_debut
    assert problem["unite"] == "dBFS" and "médiane" in problem["seuil"] and problem["action"]
    assert "aucun problème" not in audio["resultat"]
    assert "Contrôle audio : 1 alerte(s) (écart de volume entre les voix)" in credits


def test_a_working_version_reports_its_blocking_problems(real_path, tmp_path):
    segments = load_project(real_path).segments
    folder = _recordings(tmp_path / "voix", segments, {segments[0].id: 0})   # a muted file
    report, credits = _outputs(render(real_path, RenderOptions(
        moteur="humain", enregistrements=folder, annonce=False, brouillon=True),
        log=lambda _m: None))
    assert report["version_de_travail"] is True
    audio = report["controle_audio"]
    assert audio["bloquants"] == 1 and audio["par_type"]["muette"] == 1
    assert "1 problème(s) bloquant(s)" in credits and "version de travail seulement" in credits


def test_nothing_measured_means_nothing_reported(real_path):
    report = transparency_report(load_project(real_path), [], False)
    assert report["voix_utilisee"] is None and report["controle_audio"] is None

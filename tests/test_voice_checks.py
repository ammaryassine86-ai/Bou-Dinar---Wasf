"""Lot 2, fix 3: every voice is measured before the final export.

A voice that cannot be heard blocks the final export (its passage would be lost to the
viewer). Clipping, a level far from the other voices, speech much shorter than its text and
long silences at the edges are warnings, with the measured value, the threshold and what to
do. Nothing is corrected unless asked: « --couper-silences » removes the silence before and
after a voice, never inside it. The film itself is never analysed, so its own silences and
music cannot raise a false alarm."""
import json
from pathlib import Path

import numpy as np
import pytest

from wasf import media
from wasf.mix import (
    CLIP_ALERT,
    EDGE_SILENCE,
    LEVEL_GAP_DB,
    SILENT_PEAK_DB,
    TRIM_MARGIN,
    measure_voice,
    quality_problems,
    trim_silence,
)
from wasf.pipeline import RenderError, RenderOptions, render
from wasf.project import load_project, now_iso, save_project
from wasf.tts import estimated_seconds

RATE = 48000
DIRECTOR = "Réalisatrice A"


def _speech(seconds: float, amplitude: float = 0.3) -> np.ndarray:
    """Something shaped like speech: a voiced tone opening and closing four times a second."""
    t = np.arange(int(seconds * RATE)) / RATE
    syllables = 0.55 + 0.45 * np.abs(np.sin(np.pi * 4.0 * t))
    fade = np.minimum(1.0, np.minimum(t, seconds - t) / 0.03)
    return (amplitude * np.sin(2 * np.pi * 220 * t) * syllables * fade).astype(np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), dtype=np.float32)


def _pcm(samples: np.ndarray) -> np.ndarray:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")


def _placed(vid: str, samples: np.ndarray, text_seconds: float = 0.0, **extra) -> dict:
    """A placed voice as build_mix records it, with its measurements."""
    pcm = _pcm(samples)
    measured = measure_voice(pcm, RATE)
    speech = pcm.size / RATE - measured["silence_debut_s"] - measured["silence_fin_s"]
    return {"id": vid, "debut_s": 1.0, **measured, "duree_parole_s": round(max(0.0, speech), 2),
            "duree_texte_s": text_seconds, **extra}


def _codes(problems: list[dict]) -> list[tuple[str, str, str]]:
    return [(p["id"], p["code"], p["gravite"]) for p in problems]


# ---------------------------------------------------------------- measurements, one by one

def test_a_normal_voice_raises_nothing():
    voices = [_placed(f"p00{i}", _speech(2.0), text_seconds=2.0) for i in range(1, 4)]
    assert quality_problems(voices) == []
    measured = voices[0]
    assert -25 < measured["niveau_db"] < -10 and measured["crete_db"] < 0
    assert measured["silence_debut_s"] < 0.1 and measured["ecretages"] == 0


def test_a_silent_voice_blocks_and_says_why():
    voices = [_placed("p001", _speech(2.0)), _placed("p002", _silence(2.0)),
              _placed("p003", 0.001 * np.random.default_rng(1).standard_normal(RATE * 2))]
    problems = quality_problems(voices)
    assert _codes(problems) == [("p002", "muette", "bloquant"), ("p003", "muette", "bloquant")]
    muted = problems[0]
    assert muted["mesure"] < SILENT_PEAK_DB and muted["unite"] == "dBFS"
    assert str(int(SILENT_PEAK_DB)) in muted["seuil"] and "micro" in muted["action"]
    assert muted["debut_s"] == 1.0 and "ne serait pas entendu" in muted["message"]


def test_a_clipped_voice_is_a_warning_with_its_count():
    clipped = np.clip(2.0 * np.sin(2 * np.pi * 220 * np.arange(RATE) / RATE), -1, 1)
    voices = [_placed("p001", _speech(1.0)), _placed("p002", clipped),
              _placed("p003", _speech(1.0))]
    problems = [p for p in quality_problems(voices) if p["code"] == "ecretage"]
    assert _codes(problems) == [("p002", "ecretage", "alerte")]
    assert problems[0]["mesure"] >= CLIP_ALERT and "crêtes" in problems[0]["unite"]
    # A loud voice that is not clipped is not one.
    assert measure_voice(_pcm(_speech(1.0, amplitude=0.95)), RATE)["ecretages"] == 0


def test_a_voice_much_quieter_or_louder_than_the_others_is_a_warning():
    voices = [_placed(f"p00{i}", _speech(1.5, 0.3)) for i in range(1, 4)]
    voices.append(_placed("p004", _speech(1.5, 0.06)))      # 14 dB quieter
    voices.append(_placed("p005", _speech(1.5, 0.24)))      # 2 dB quieter: fine
    problems = quality_problems(voices)
    assert _codes(problems) == [("p004", "volume", "alerte")]
    gap = problems[0]["ecart_db"]
    assert -15.0 < gap < -LEVEL_GAP_DB and "plus faible" in problems[0]["message"]
    assert "médiane" in problems[0]["seuil"]


def test_a_voice_far_too_short_for_its_text_is_a_warning():
    voices = [_placed("p001", _speech(0.4), text_seconds=3.0),      # a cough, a wrong file
              _placed("p002", _speech(2.0), text_seconds=3.0),      # a fast speaker: fine
              _placed("p003", _speech(0.3), text_seconds=0.6)]      # a short text: never
    problems = quality_problems(voices)
    assert _codes(problems) == [("p001", "trop_courte", "alerte")]
    assert "mauvais fichier" in problems[0]["message"]


def test_long_silence_at_the_edges_is_a_warning_unless_it_was_cut():
    late = np.concatenate([_silence(1.5), _speech(1.0), _silence(0.2)])
    voices = [_placed("p001", late), _placed("p002", _speech(1.0))]
    problems = quality_problems(voices)
    assert _codes(problems) == [("p001", "silence_debut", "alerte")]
    assert problems[0]["mesure"] > EDGE_SILENCE and "--couper-silences" in problems[0]["action"]
    voices[0]["silence_coupe_s"] = 1.6
    assert quality_problems(voices) == []


def test_an_intentional_pause_inside_a_voice_is_never_an_alarm_nor_cut():
    paused = np.concatenate([_silence(0.5), _speech(1.0), _silence(1.6), _speech(1.0),
                             _silence(0.4)])
    voice = _placed("p001", paused, text_seconds=2.5)
    assert quality_problems([voice, _placed("p002", _speech(2.0))]) == []
    pcm = _pcm(paused)
    kept = trim_silence(pcm, RATE)
    margin = int(TRIM_MARGIN * RATE)
    # Only the edges go: the pause in the middle and both stretches of speech are intact.
    start = int(0.5 * RATE) - margin
    assert np.array_equal(kept, pcm[start:start + kept.size])
    assert abs(kept.size / RATE - (1.0 + 1.6 + 1.0 + 2 * TRIM_MARGIN)) < 0.05
    assert trim_silence(_pcm(_silence(1.0)), RATE).size == RATE      # no speech: untouched


# ---------------------------------------------------------------- in a real export

def _approve(path: Path) -> list:
    project = load_project(path)
    project.realisateur = DIRECTOR
    for seg in project.segments:
        seg.statut, seg.valide_par, seg.valide_le = "valide", DIRECTOR, now_iso()
    project.validation_realisateur, project.approuve_par = True, DIRECTOR
    save_project(project, path)
    return project.segments


def _length(seg) -> float:
    """How long a person takes to read the passage, within its pause."""
    return min(0.9 * seg.duree_parole, max(0.6, estimated_seconds(seg.texte, "fr")))


def _record(folder: Path, segments: list, special: dict) -> None:
    """One recording per passage, read at a normal pace; `special` replaces some of them."""
    for seg in segments:
        samples = special.get(seg.id)
        if samples is None:
            samples = _speech(_length(seg))
        media.write_wav(folder / f"{seg.id}.wav", samples, RATE)


def _export(path: Path, folder: Path, logs: list[str], **options):
    opts = RenderOptions(moteur="humain", enregistrements=folder, annonce=False, **options)
    return render(path, opts, log=logs.append)


def test_a_muted_recording_stops_the_final_export_but_not_a_working_version(real_path,
                                                                            tmp_path):
    segments = _approve(real_path)
    target = segments[1]
    folder = tmp_path / "voix"
    _record(folder, segments, {target.id: _silence(min(0.8, 0.6 * target.duree_parole))})
    logs: list[str] = []
    with pytest.raises(RenderError) as refused:
        _export(real_path, folder, logs)
    message = str(refused.value)
    assert message.startswith("Export refusé : une voix est muette ou presque.")
    assert f"{target.id} : voix muette ou presque" in message and "--brouillon" in message
    assert not (real_path.parent / "export" / "piste_audiodecrite.wav").exists()
    project = load_project(real_path)
    assert project.historique[-1]["action"] == "export_refuse"
    assert project.historique[-1]["raison"] == "voix muette"
    assert project.segment(target.id).voix_mesuree["alertes"] == ["muette"]

    logs.clear()
    outputs = _export(real_path, folder, logs, brouillon=True)
    assert outputs["film"].exists()
    assert any(line.strip().startswith(f"Bloquant : {target.id} : voix muette") for line in logs)


def test_warnings_never_stop_the_final_export(real_path, tmp_path):
    segments = _approve(real_path)
    loud, quiet = segments[0], segments[2]
    length = int(min(0.8, 0.6 * loud.duree_parole) * RATE)
    clipped = np.clip(2.0 * np.sin(2 * np.pi * 220 * np.arange(length) / RATE), -1, 1)
    folder = tmp_path / "voix"
    _record(folder, segments, {loud.id: clipped.astype(np.float32),
                               quiet.id: _speech(_length(quiet), 0.03)})
    logs: list[str] = []
    outputs = _export(real_path, folder, logs)
    assert outputs["film"].exists()
    alerts = [line.strip() for line in logs if line.strip().startswith("Alerte :")]
    assert any(f"{loud.id} : son saturé" in line for line in alerts)
    assert any(f"{quiet.id} : voix plus faible" in line for line in alerts)
    project = load_project(real_path)
    assert "ecretage" in project.segment(loud.id).voix_mesuree["alertes"]
    assert project.segment(quiet.id).voix_mesuree["alertes"] == ["volume"]
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    measured = {v["id"]: v for v in report["voix"]}
    assert measured[quiet.id]["niveau_db"] < measured[segments[1].id]["niveau_db"] - LEVEL_GAP_DB


def test_cutting_the_silence_is_asked_for_and_keeps_the_speech(real_path, tmp_path):
    segments = _approve(real_path)
    target = min(segments, key=lambda s: s.duree_parole)
    window = target.duree_parole
    lead = 0.02 * round(1.2 * window / 0.02)               # on a 20 ms frame, like the detector
    spoken = _speech(0.5 * window)
    late = np.concatenate([_silence(lead), spoken, _silence(0.3)])
    folder = tmp_path / "voix"
    _record(folder, segments, {target.id: late})

    logs: list[str] = []
    with pytest.raises(RenderError) as refused:             # as recorded: far too long
        _export(real_path, folder, logs)
    message = str(refused.value)
    assert f"{target.id} :" in message and "déborde" in message
    assert "de silence au début" in message and "--couper-silences" in message

    logs.clear()
    outputs = _export(real_path, folder, logs, couper_silences=True)
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    voice = {v["id"]: v for v in report["voix"]}[target.id]
    assert voice["silence_coupe_s"] > lead and not voice["deborde"]
    assert abs(voice["silence_debut_s"] - lead) < 0.03            # what the recording had
    placed = media.decode_pcm16(outputs["film"].parent / "voix" / f"{target.id}.wav", RATE, 1)
    placed = placed[:, 0].astype(np.int32)
    original = _pcm(spoken).astype(np.int32)
    margin = int(TRIM_MARGIN * RATE)
    # The speech is the recording's own, sample for sample (±1 for the 16-bit rewrite).
    core = placed[margin:margin + original.size]
    assert core.size == original.size and np.max(np.abs(core - original)) <= 1


def test_the_films_own_silences_and_music_raise_nothing(real_path):
    """The demo film has silences and sound of its own: only the voices are measured."""
    _approve(real_path)
    logs: list[str] = []
    outputs = render(real_path, RenderOptions(moteur="bip", annonce=False), log=logs.append)
    assert not any(line.strip().startswith(("Alerte", "Bloquant")) for line in logs)
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    assert all(v["alertes"] == [] for v in report["voix"])

"""T24 · A spoken description must never run over the actors or into another description.

The editor shows each passage's estimated spoken length and, after an export, the measured
one. The final export refuses a voice that overruns its pause or runs into the next voice;
a working version (--brouillon) is still produced, with the problems listed."""
import json
import random
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from editeur_client import editor_client

import wasf.mix as mixmod
from wasf import media
from wasf.agent import review_flags
from wasf.gaps import Cue, parse_subtitles, plan_windows
from wasf.mix import VoiceTimingError, build_mix, timing_problems
from wasf.pipeline import RenderError, RenderOptions, render
from wasf.project import Segment, load_project, now_iso, save_project
from wasf.tts import WORDS_PER_SECOND, estimated_seconds


def _approve(path: Path) -> None:
    project = load_project(path)
    project.realisateur = "Réalisatrice A"
    for seg in project.segments:
        seg.statut, seg.valide_par, seg.valide_le = "valide", "Réalisatrice A", now_iso()
    project.validation_realisateur, project.approuve_par = True, "Réalisatrice A"
    save_project(project, path)


def _slow_voice(factor: float):
    """A voice engine `factor` times slower than the word budget assumes."""
    def synthesize(engine, text, out_wav, *, langue, voix=None, segment_id="",
                   enregistrements=None, sample_rate=48000):
        seconds = factor * max(0.6, len(text.split()) / WORDS_PER_SECOND[langue])
        t = np.arange(int(seconds * sample_rate)) / sample_rate
        media.write_wav(Path(out_wav), (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32),
                        sample_rate)
        return Path(out_wav)
    return synthesize


def _editor(path: Path):
    return editor_client(path)


def test_final_export_refuses_a_voice_that_overruns(real_path, monkeypatch):
    _approve(real_path)
    monkeypatch.setattr(mixmod, "synthesize", _slow_voice(3.0))
    with pytest.raises(RenderError) as refused:
        render(real_path, RenderOptions(moteur="bip", annonce=False), log=lambda _m: None)
    message = str(refused.value)
    assert "déborde" in message and "--brouillon" in message and "p001" in message
    assert not (real_path.parent / "export" / "film_audiodecrit.mp4").exists()
    assert not (real_path.parent / "export" / "piste_audiodecrite.wav").exists()
    project = load_project(real_path)
    assert project.historique[-1]["action"] == "export_refuse"
    for seg in project.segments:
        assert seg.voix_mesuree["deborde"] and seg.voix_mesuree["texte"] == seg.texte
        assert seg.voix_mesuree["depassement_s"] > 0.05
        assert "voix trop longue" in review_flags(seg)


def test_working_version_is_still_made_and_lists_the_overruns(real_path, monkeypatch):
    monkeypatch.setattr(mixmod, "synthesize", _slow_voice(3.0))
    logs = []
    outputs = render(real_path, RenderOptions(moteur="bip", brouillon=True, annonce=False),
                     log=logs.append)
    assert outputs["film"].exists()
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    assert report["version_de_travail"] is True
    assert report["voix_hors_pause"] == [v["id"] for v in report["voix"]]
    assert all(v["deborde"] for v in report["voix"])
    assert sum("dépasse la pause" in line for line in logs) == len(report["voix"])


def test_final_export_keeps_every_voice_inside_its_pause(real_path, demo_files):
    _approve(real_path)
    outputs = render(real_path, RenderOptions(moteur="bip", annonce=False), log=lambda _m: None)
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    project = load_project(real_path)
    cues = parse_subtitles(demo_files["sous_titres"])
    voices = sorted(report["voix"], key=lambda v: v["debut_s"])
    assert voices and report["voix_hors_pause"] == []
    for voice in voices:
        seg = project.segment(voice["id"])
        start, end = voice["debut_s"], voice["fin_voix_s"]
        assert seg.debut <= start and end <= seg.fin            # inside its own pause
        assert end <= voice["limite_s"] + 0.05
        for cue in cues:                                         # never over a line of dialogue
            assert end <= cue.start or start >= cue.end, (voice["id"], cue)
    for current, following in pairwise(voices):           # never over another voice
        assert current["fin_voix_s"] <= following["debut_s"]
    for seg in project.segments:                                 # the measurement is kept
        assert seg.voix_mesuree["deborde"] is False and "voix trop longue" not in review_flags(seg)


def test_voices_that_run_into_each_other_are_refused(tmp_path):
    film = tmp_path / "film.mp4"
    media.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
               "color=c=gray:s=64x36:r=5:d=12", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", str(film)])
    # Two pauses that overlap (a hand-edited project): each voice fits its own pause.
    segments = [Segment(id="p001", debut=0.7, fin=6.3, parole_debut=1.0, parole_fin=6.0,
                        budget_mots=14, texte="Une rue étroite, des volets bleus et du linge."),
                Segment(id="p002", debut=2.7, fin=8.3, parole_debut=3.0, parole_fin=8.0,
                        budget_mots=14, texte="Un chat traverse la rue.")]
    with pytest.raises(VoiceTimingError) as refused:
        build_mix(film, segments, tmp_path / "out", langue="fr", moteur="bip", voix=None,
                  enregistrements=None, duree=12.0, log=lambda _m: None, strict=True)
    assert [(p["id"], p["code"]) for p in refused.value.problems] == [("p001", "chevauche")]
    assert not (tmp_path / "out" / "piste_audiodecrite.wav").exists()
    draft = build_mix(film, segments, tmp_path / "brouillon", langue="fr", moteur="bip",
                      voix=None, enregistrements=None, duree=12.0, log=lambda _m: None)
    assert draft["piste_mixee"].exists() and draft["passages"][0]["chevauche"] == "p002"


def test_timing_rules():
    def voice(i, start, end, limit, pause_end, overflow):
        return {"id": i, "debut_s": start, "fin_voix_s": end, "limite_s": limit,
                "fin_pause_s": pause_end, "duree_voix_s": end - start,
                "duree_disponible_s": limit - start, "acceleration": 1.0,
                "depassement_s": overflow, "deborde": overflow > 0.05, "chevauche": ""}
    assert timing_problems([voice("a", 1.0, 3.0, 3.0, 3.3, 0.0),
                            voice("b", 4.0, 6.0, 6.2, 6.5, 0.0)]) == []
    over = timing_problems([voice("a", 1.0, 3.9, 3.0, 3.3, 0.9)])
    assert [p["code"] for p in over] == ["deborde"] and "sur le dialogue" in over[0]["message"]
    margin = timing_problems([voice("a", 1.0, 3.2, 3.0, 3.3, 0.2)])
    assert "dans la marge" in margin[0]["message"]
    assert [p["code"] for p in timing_problems([voice("a", 1.0, 4.5, 6.0, 6.3, 0.0),
                                                voice("b", 4.0, 5.0, 6.0, 6.3, 0.0)])] == ["chevauche"]


def test_planned_pauses_never_overlap_dialogue_or_each_other():
    rng = random.Random(24)
    margin = 0.3
    for _ in range(300):
        total = rng.uniform(20, 200)
        cues = []
        for _ in range(rng.randint(0, 40)):
            start = rng.uniform(0, total)
            cues.append(Cue(start, min(total, start + rng.uniform(0.2, 6)), "réplique"))
        rng.shuffle(cues)                     # unsorted, some overlapping each other
        cues.sort(key=lambda c: c.start)      # as parse_subtitles returns them
        spoken = [(w.start + margin, w.end - margin)
                  for w in plan_windows(total, cues=cues, min_gap=1.6, max_len=8.0)]
        for start, end in spoken:
            for cue in cues:
                assert end <= cue.start or start >= cue.end
        for (_, end), (start, _) in pairwise(spoken):
            assert end <= start


def test_editor_shows_the_estimate_and_the_measured_voice(real_path, monkeypatch):
    _approve(real_path)
    monkeypatch.setattr(mixmod, "synthesize", _slow_voice(3.0))
    with pytest.raises(RenderError):
        render(real_path, RenderOptions(moteur="bip", annonce=False), log=lambda _m: None)
    client = _editor(real_path)
    data = client.get("/api/projet").get_json()
    assert data["mots_par_seconde"] == WORDS_PER_SECOND["fr"]
    seg = data["segments"][0]
    assert seg["duree_estimee"] == round(estimated_seconds(seg["texte"], "fr"), 1)
    assert seg["voix_a_jour"] and seg["voix_mesuree"]["deborde"]
    assert "voix trop longue" in seg["signalements"]
    # A shorter text: the old measurement no longer applies, the warning goes away.
    shorter = "Un carré."
    assert shorter != seg["texte"]
    answer = client.post(f"/api/passage/{seg['id']}", json={"action": "enregistrer",
                                                          "texte": shorter})
    assert answer.status_code == 200
    seg = answer.get_json()["passage"]
    assert not seg["voix_a_jour"] and "voix trop longue" not in seg["signalements"]
    assert all(c["code"] != "voix_trop_longue" for c in seg["verifications"])
    assert seg["duree_estimee"] == round(2 / WORDS_PER_SECOND["fr"], 1)

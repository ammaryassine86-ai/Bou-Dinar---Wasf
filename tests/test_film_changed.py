"""Lot 2, fix 4: a final export refuses a video that no longer matches the one the track was
prepared on, and a passage is never dropped in silence because the film ends before it.

Before: with a shorter video, the passages after its end were skipped with one line in the log,
even in a final export, and a voice running past the end was cut without a word."""
from pathlib import Path

import pytest

from wasf import media, pipeline
from wasf.mix import VoiceTimingError, build_mix
from wasf.pipeline import RenderError, RenderOptions, _relative, render
from wasf.project import Segment, load_project, now_iso, save_project

DIRECTOR = "Réalisatrice A"


def _approve(path: Path) -> None:
    project = load_project(path)
    project.realisateur = DIRECTOR
    for seg in project.segments:
        seg.statut, seg.valide_par, seg.valide_le = "valide", DIRECTOR, now_iso()
    project.validation_realisateur, project.approuve_par = True, DIRECTOR
    save_project(project, path)


def _swap_video(path: Path, video: Path) -> None:
    """What happens when someone replaces the film next to the project."""
    project = load_project(path)
    project.video = _relative(video, path.parent)
    save_project(project, path)


def _cut(source: Path, out: Path, seconds: float | None = None) -> Path:
    """The same film re-encoded, whole or only its first `seconds`."""
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source)]
    if seconds is not None:
        command += ["-t", str(seconds)]
    media.run(command + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                         "-c:a", "aac", str(out)])
    return out


def test_a_shorter_video_stops_the_final_export(real_path, demo_files, tmp_path):
    _approve(real_path)
    project = load_project(real_path)
    late = [s.id for s in project.segments if s.parole_debut >= 20.0]
    assert late, "the demo has passages after 20 s"
    _swap_video(real_path, _cut(demo_files["video"], tmp_path / "court.mp4", 20.0))

    with pytest.raises(RenderError) as refused:
        render(real_path, RenderOptions(moteur="bip", annonce=False), log=lambda _m: None)
    message = str(refused.value)
    assert message.startswith("Export refusé : la vidéo a changé depuis la préparation")
    assert "court.mp4 dure 20,0 s" in message and "30,0 s" in message
    assert "--brouillon" in message
    assert not (real_path.parent / "export").exists()


def test_a_working_version_goes_on_and_names_the_lost_passages(real_path, demo_files,
                                                               tmp_path):
    project = load_project(real_path)
    late = [s.id for s in project.segments if s.parole_debut >= 20.0]
    _swap_video(real_path, _cut(demo_files["video"], tmp_path / "court.mp4", 20.0))
    logs: list[str] = []
    outputs = render(real_path, RenderOptions(moteur="bip", annonce=False, brouillon=True),
                     log=logs.append)
    assert outputs["film"].exists()
    assert any(line.startswith("Attention : la vidéo court.mp4 dure 20,0 s") for line in logs)
    for seg_id in late:                     # each lost passage is named, never skipped quietly
        assert any(line.strip().startswith(f"Bloquant : {seg_id} : commence à")
                   and "après la fin du film (20,0 s)" in line for line in logs), seg_id


def test_the_same_film_re_encoded_still_exports(real_path, demo_files, tmp_path):
    _approve(real_path)
    copy = _cut(demo_files["video"], tmp_path / "meme_film.mp4")
    assert abs(media.duration(copy) - load_project(real_path).duree) < 0.5
    _swap_video(real_path, copy)
    outputs = render(real_path, RenderOptions(moteur="bip", annonce=False), log=lambda _m: None)
    assert outputs["film"].exists()


def _gray_film(path: Path, seconds: float) -> Path:
    media.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
               f"color=c=gray:s=64x36:r=5:d={seconds}", "-c:v", "libx264", "-preset",
               "ultrafast", "-pix_fmt", "yuv420p", str(path)])
    return path


def test_a_passage_after_the_end_of_the_film_is_never_dropped_quietly(tmp_path):
    film = _gray_film(tmp_path / "film.mp4", 12)
    segments = [Segment(id="p001", debut=0.7, fin=4.3, parole_debut=1.0, parole_fin=4.0,
                        budget_mots=8, texte="Une rue étroite."),
                Segment(id="p002", debut=12.7, fin=16.3, parole_debut=13.0, parole_fin=16.0,
                        budget_mots=8, texte="Un chat traverse.")]
    with pytest.raises(VoiceTimingError) as refused:
        build_mix(film, segments, tmp_path / "final", langue="fr", moteur="bip", voix=None,
                  enregistrements=None, duree=12.0, log=lambda _m: None, strict=True)
    assert [(p["id"], p["code"], p["gravite"]) for p in refused.value.problems] == [
        ("p002", "hors_film", "bloquant")]
    lost = refused.value.problems[0]
    assert lost["mesure"] == 13.0 and "12,0 s" in lost["seuil"] and "perdu" in lost["message"]

    draft = build_mix(film, segments, tmp_path / "travail", langue="fr", moteur="bip",
                      voix=None, enregistrements=None, duree=12.0, log=lambda _m: None)
    assert [v["id"] for v in draft["passages"]] == ["p001"]
    assert [(c["id"], c["code"]) for c in draft["controles"]] == [("p002", "hors_film")]


def test_a_voice_the_end_of_the_film_would_cut_is_named(tmp_path):
    film = _gray_film(tmp_path / "film.mp4", 12)
    # The pause (as prepared on a longer film) ends after this one: the voice fits its pause
    # but not the film.
    segments = [Segment(id="p001", debut=10.0, fin=13.0, parole_debut=10.3, parole_fin=12.7,
                        budget_mots=6, texte="Un chat noir traverse la rue.")]
    with pytest.raises(VoiceTimingError) as refused:
        build_mix(film, segments, tmp_path / "final", langue="fr", moteur="bip", voix=None,
                  enregistrements=None, duree=12.0, log=lambda _m: None, strict=True)
    problem = refused.value.problems[0]
    assert (problem["id"], problem["code"]) == ("p001", "coupee")
    assert problem["mesure"] > 0.05 and "couperait" in problem["message"]


def test_the_refusal_says_what_to_do_for_a_lost_passage(real_path, monkeypatch):
    """When a final export stops on a passage the film cannot hold, the advice fits."""
    _approve(real_path)
    project = load_project(real_path)
    first = project.segments[0]

    def build_mix_with_a_lost_passage(*_args, **_kwargs):
        raise VoiceTimingError([{"id": first.id, "code": "hors_film",
                                 "message": f"{first.id} : commence après la fin du film."}],
                               [])

    monkeypatch.setattr(pipeline, "build_mix", build_mix_with_a_lost_passage)
    with pytest.raises(RenderError) as refused:
        render(real_path, RenderOptions(moteur="bip", annonce=False), log=lambda _m: None)
    message = str(refused.value)
    assert message.startswith("Export refusé : un passage tombe après la fin du film.")
    assert "Vérifiez que la vidéo est bien celle de la préparation" in message
    assert load_project(real_path).historique[-1]["raison"] == "passage hors du film"

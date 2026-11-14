"""Lot 2, fix 2: with the human voice, every recording is looked at before the export starts,
and everything missing or unreadable is named at once.

The export used to stop at the first missing file: add it, run again, stop at the next one."""
import json
from pathlib import Path

import pytest

from wasf import media
from wasf.export import label_text
from wasf.pipeline import RenderError, RenderOptions, render
from wasf.project import load_project, now_iso, save_project
from wasf.tts import find_recording

DIRECTOR = "Réalisatrice A"


def _approve(path: Path) -> list[str]:
    project = load_project(path)
    project.realisateur = DIRECTOR
    for seg in project.segments:
        seg.statut, seg.valide_par, seg.valide_le = "valide", DIRECTOR, now_iso()
    project.validation_realisateur, project.approuve_par = True, DIRECTOR
    save_project(project, path)
    return [seg.id for seg in project.segments]


def _tone(path: Path, seconds: float = 0.6) -> Path:
    """A short recording in the format its name says (.wav, .m4a, .mp3…)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    media.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
               f"sine=frequency=330:duration={seconds}", "-ac", "1", str(path)])
    return path


def _final(path: Path, folder: Path | None, logs: list[str] | None = None, **options):
    opts = RenderOptions(moteur="humain", enregistrements=folder, **{"annonce": False, **options})
    return render(path, opts, log=(logs.append if logs is not None else lambda _m: None))


def test_recordings_from_a_phone_are_found_whatever_their_format_and_case(real_path, tmp_path):
    ids = _approve(real_path)
    folder = tmp_path / "voix"
    formats = [".wav", ".m4a", ".mp3", ".ogg", ".opus", ".flac"]
    for i, seg_id in enumerate(ids):
        name = seg_id + formats[i % len(formats)]
        _tone(folder / (name.upper() if i == 2 else name))     # P003.MP3: a phone's capitals
    outputs = _final(real_path, folder)
    assert outputs["film"].exists()
    for seg_id in ids:
        assert (outputs["film"].parent / "voix" / f"{seg_id}.wav").exists()


def test_everything_missing_or_unreadable_is_named_at_once(real_path, tmp_path):
    ids = _approve(real_path)
    assert len(ids) >= 4
    folder = tmp_path / "voix"
    _tone(folder / f"{ids[0]}.m4a")
    (folder / f"{ids[2]}.wav").write_bytes(b"pas du son")                  # unreadable
    _tone(folder / f"{ids[3]}.wav", seconds=0.01)                          # next to nothing
    for seg_id in ids[4:]:
        _tone(folder / f"{seg_id}.wav")
    _tone(folder / "p2.m4a")                                               # misnamed p002
    (folder / f"{ids[1]}.amr").write_bytes(b"#!AMR\n")                     # unsupported format
    (folder / "desktop.ini").write_text("[.ShellClassInfo]")               # Windows' own file

    with pytest.raises(RenderError) as refused:
        _final(real_path, folder)
    message = str(refused.value)
    assert f"manquants (1) : {ids[1]}" in message
    assert f"inutilisables (2) : {ids[2]}.wav (illisible), {ids[3]}.wav (vide)" in message
    assert f"{ids[1]}.wav, ou .mp3, .m4a, .ogg, .flac, .opus" in message
    assert f"ne servent à aucun passage (nom ou format) : {ids[1]}.amr, p2.m4a" in message
    assert "desktop.ini" not in message
    # Nothing was started: no export folder, no log line in the project.
    assert not (real_path.parent / "export").exists()
    assert load_project(real_path).historique[-1]["action"] != "export"


def test_a_working_version_needs_its_recordings_too(real_path, tmp_path):
    project = load_project(real_path)
    folder = tmp_path / "voix"
    _tone(folder / f"{project.segments[0].id}.wav")
    with pytest.raises(RenderError) as refused:
        _final(real_path, folder, brouillon=True)
    missing = [seg.id for seg in project.segments[1:] if seg.statut != "ignore"]
    assert f"manquants ({len(missing)}) : {', '.join(missing)}" in str(refused.value)


def test_no_folder_or_a_wrong_folder_is_said_plainly(real_path, tmp_path):
    _approve(real_path)
    with pytest.raises(RenderError, match="indiquez le dossier des enregistrements"):
        _final(real_path, None)
    with pytest.raises(RenderError, match="Dossier des enregistrements introuvable"):
        _final(real_path, tmp_path / "nulle-part")


def test_a_missing_announcement_leaves_the_card_silent_and_says_what_to_record(real_path,
                                                                               tmp_path):
    ids = _approve(real_path)
    folder = tmp_path / "voix"
    for seg_id in ids:
        _tone(folder / f"{seg_id}.wav")
    logs: list[str] = []
    outputs = _final(real_path, folder, logs, annonce=True)
    sentence = label_text(load_project(real_path))
    warning = [line for line in logs if "carton d'annonce" in line]
    assert len(warning) == 1 and "annonce.wav absent" in warning[0] and sentence in warning[0]
    assert outputs["film"].exists()

    (folder / "annonce.wav").write_bytes(b"abime")      # unreadable: used to crash at the end
    logs.clear()
    outputs = _final(real_path, folder, logs, annonce=True)
    assert outputs["film"].exists()
    assert any("annonce.wav illisible" in line for line in logs)

    _tone(folder / "annonce.wav", seconds=2.0)
    logs.clear()
    outputs = _final(real_path, folder, logs, annonce=True)
    assert not any("carton d'annonce" in line for line in logs)
    spoken = media.duration(outputs["film"].parent / "annonce.wav")
    assert abs(spoken - 2.0) < 0.1
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    assert report["mention"] == sentence


def test_which_file_is_a_passage_recording(tmp_path):
    folder = tmp_path / "voix"
    assert find_recording(folder, "p001") is None                    # no folder yet
    _tone(folder / "p001.m4a")
    assert find_recording(folder, "p001").name == "p001.m4a"
    _tone(folder / "p001.wav")
    assert find_recording(folder, "p001").name == "p001.wav"         # .wav first, as before
    _tone(folder / "P002.MP3")
    assert find_recording(folder, "p002").name == "P002.MP3"
    assert find_recording(folder, "p003") is None
    _tone(folder / "p0031.wav")
    assert find_recording(folder, "p003") is None                    # never a near match

"""Lot 3, point O: the preparation records the video file's fingerprint, and the export compares
it. A replaced film is reported even when it has the same length, which the length check alone
missed. It is a warning, not a refusal: a re-encoded copy of the same edit changes the
fingerprint too, and must still export (see test_film_changed)."""
import json
import shutil
from pathlib import Path

from wasf import media
from wasf.pipeline import RenderOptions, _relative, render
from wasf.project import load_project, now_iso, save_project

DIRECTOR = "Réalisatrice A"


def _approve(path: Path) -> None:
    project = load_project(path)
    project.realisateur = DIRECTOR
    for seg in project.segments:
        seg.statut, seg.valide_par, seg.valide_le = "valide", DIRECTOR, now_iso()
    project.validation_realisateur, project.approuve_par = True, DIRECTOR
    save_project(project, path)


def _use_video(path: Path, video: Path) -> None:
    project = load_project(path)
    project.video = _relative(video, path.parent)
    save_project(project, path)


def _export(path: Path) -> tuple[dict, list[str]]:
    logs: list[str] = []
    outputs = render(path, RenderOptions(moteur="bip", annonce=False), log=logs.append)
    return json.loads(outputs["rapport"].read_text(encoding="utf-8")), logs


def test_the_fingerprint_follows_the_bytes(tmp_path):
    film = tmp_path / "film.bin"
    film.write_bytes(bytes(range(256)) * 20_000)                # about 5 MB
    copy = tmp_path / "copie.bin"
    shutil.copyfile(film, copy)
    assert media.fingerprint(film) == media.fingerprint(copy)
    data = bytearray(film.read_bytes())
    data[len(data) // 2] ^= 0xFF                                   # one byte, in the middle
    copy.write_bytes(bytes(data))
    assert media.fingerprint(film) != media.fingerprint(copy)


def test_the_preparation_records_it(real_path, demo_files):
    project = load_project(real_path)
    assert project.empreinte_film == media.fingerprint(demo_files["video"])


def test_the_same_film_is_said_to_be_the_same(real_path):
    _approve(real_path)
    report, logs = _export(real_path)
    assert report["controle_du_film"]["identique"] is True
    assert not any("n'est plus le même" in line for line in logs)


def test_a_replaced_film_of_the_same_length_is_reported(real_path, demo_files, tmp_path):
    _approve(real_path)
    other = tmp_path / "autre_montage.mp4"     # same streams, other file: same length exactly
    media.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(demo_files["video"]), "-c", "copy",
               "-metadata", "title=autre montage", str(other)])
    assert abs(media.duration(other) - load_project(real_path).duree) < 0.5
    _use_video(real_path, other)
    report, logs = _export(real_path)                            # a warning, not a refusal
    check = report["controle_du_film"]
    assert check["identique"] is False
    assert check["empreinte_preparation"] != check["empreinte_export"]
    assert any("n'est plus le même qu'à la préparation" in line for line in logs)
    assert load_project(real_path).historique[-1]["film_modifie_depuis_preparation"] is True


def test_a_project_made_before_says_only_the_length_was_compared(real_path):
    _approve(real_path)
    project = load_project(real_path)
    project.empreinte_film = ""
    save_project(project, real_path)
    report, logs = _export(real_path)
    assert report["controle_du_film"]["identique"] is None
    assert "seule la durée" in report["controle_du_film"]["remarque"]
    assert not any("n'est plus le même" in line for line in logs)

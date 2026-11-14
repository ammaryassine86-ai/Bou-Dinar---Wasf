"""Lot 2, fix 6: a damaged projet.json gets a plain message, never a Python traceback.

The message says which file, what is wrong in it and where its backups are. The file is left
exactly as it was; the review editor refuses to start on it, or says so on the page if it gets
damaged while the editor is open."""
import json
import shutil
from pathlib import Path

import pytest
from editeur_client import editor_client

from wasf.cli import main
from wasf.project import ProjectFileError, load_project


def _damage(path: Path, content: bytes) -> bytes:
    path.write_bytes(content)
    return content


def _cli(capsys, *args) -> tuple[int, str]:
    code = main([str(a) for a in args])
    captured = capsys.readouterr()
    return code, captured.err


@pytest.mark.parametrize("content, why", [
    (b'{"film": "x", "segments": [', "JSON invalide à la ligne 1, colonne 28"),
    (b"", "JSON invalide à la ligne 1, colonne 1"),
    (b'\xff\xfe{"film": "x"}', "ce n'est pas du texte UTF-8"),
    (b'["une", "liste"]', "ce n'est pas un projet Wasf"),
    (b'{"film": "x", "segments": "aucun"}', "ce n'est pas un projet Wasf"),
])
def test_a_damaged_project_is_explained_not_traced(real_path, capsys, content, why):
    before = _damage(real_path, content)
    code, err = _cli(capsys, "exporter", real_path, "--voix-moteur", "bip")
    assert code == 1
    assert err.startswith(f"Erreur : Projet illisible : {real_path} ({why})")
    assert "Traceback" not in err and "remettez une copie de projet.json" in err
    assert real_path.read_bytes() == before                  # left exactly as it was


def test_a_project_with_a_broken_passage_is_explained(real_path):
    data = json.loads(real_path.read_text(encoding="utf-8"))
    del data["segments"][0]["id"]
    real_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProjectFileError, match="champ manquant ou mal formé"):
        load_project(real_path)
    data["segments"][0] = "pas un passage"
    real_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProjectFileError, match="champ manquant ou mal formé"):
        load_project(real_path)


def test_the_backups_are_named(real_path):
    backup = real_path.parent / "sauvegarde-20261113-101500"
    backup.mkdir()
    shutil.copy(real_path, backup / "projet.json")
    _damage(real_path, b"{")
    with pytest.raises(ProjectFileError) as refused:
        load_project(real_path)
    assert "sauvegarde-20261113-101500/projet.json" in str(refused.value)
    assert "s'ouvrent dans l'éditeur" in str(refused.value)
    assert load_project(backup / "projet.json").segments               # the backup is fine


def test_the_editor_does_not_start_on_a_damaged_project(real_path, capsys):
    _damage(real_path, b"{")
    code, err = _cli(capsys, "relire", real_path, "--sans-navigateur")
    assert code == 1 and err.startswith("Erreur : Projet illisible")


def test_the_editor_says_so_if_the_project_is_damaged_while_open(real_path):
    client = editor_client(real_path)
    assert client.get("/api/projet").status_code == 200
    _damage(real_path, b'{"film": ')
    answer = client.get("/api/projet")
    assert answer.status_code == 500
    assert answer.get_json()["erreur"].startswith("Projet illisible")
    edit = client.post("/api/passage/p001", json={"action": "enregistrer", "texte": "x"})
    assert edit.status_code == 500 and real_path.read_bytes() == b'{"film": '

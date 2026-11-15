"""Phase 0 : la garde de version de projet.json.

Wasf ignore à la lecture les champs qu'il ne connaît pas, et ne les réécrit pas. Un projet
d'un format plus récent est donc refusé, à l'ouverture comme à l'enregistrement : une version
ancienne ne peut pas effacer ce qu'elle ne connaît pas. Un projet du format actuel s'ouvre,
s'enregistre et se relit à l'identique."""
import json

import pytest

from wasf.cli import main
from wasf.project import SCHEMA_VERSION, ProjectFileError, load_project, save_project


def _with_version(path, version) -> bytes:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version_schema"] = version
    data["faits"] = [{"id": "f0001", "texte": "Salma glisse la lettre dans le tiroir"}]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path.read_bytes()


def test_a_project_round_trips_unchanged(real_path, tmp_path):
    copy = tmp_path / "copie" / "projet.json"
    save_project(load_project(real_path), copy)
    assert copy.read_bytes() == real_path.read_bytes()


def test_a_newer_project_is_refused_and_left_as_it_is(real_path):
    before = _with_version(real_path, SCHEMA_VERSION + 1)
    with pytest.raises(ProjectFileError, match="Projet trop récent") as refused:
        load_project(real_path)
    assert f"au format {SCHEMA_VERSION + 1}" in str(refused.value)
    assert "Mettez Wasf à jour" in str(refused.value)
    assert real_path.read_bytes() == before                    # left exactly as it was


def test_a_newer_project_is_never_written(real_path):
    before = real_path.read_bytes()
    project = load_project(real_path)
    project.version_schema = SCHEMA_VERSION + 1
    with pytest.raises(ProjectFileError, match="Projet trop récent"):
        save_project(project, real_path)
    assert real_path.read_bytes() == before
    assert not list(real_path.parent.glob(".projet-*"))        # no temporary file left behind


@pytest.mark.parametrize("version", ["2", True, 0, -1, 1.5, None])
def test_a_malformed_version_is_explained(real_path, version):
    _with_version(real_path, version)
    with pytest.raises(ProjectFileError, match="Projet illisible.*version_schema"):
        load_project(real_path)


def test_a_project_without_a_version_opens_as_the_first_format(real_path):
    data = json.loads(real_path.read_text(encoding="utf-8"))
    del data["version_schema"]
    real_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert load_project(real_path).version_schema == 1


@pytest.mark.parametrize("command", [["relire", "--sans-navigateur"],
                                     ["exporter", "--voix-moteur", "bip"]])
def test_the_editor_and_the_export_say_so(real_path, capsys, command):
    before = _with_version(real_path, SCHEMA_VERSION + 1)
    code = main([command[0], str(real_path), *command[1:]])
    err = capsys.readouterr().err
    assert code == 1 and err.startswith("Erreur : Projet trop récent")
    assert "Traceback" not in err
    assert real_path.read_bytes() == before

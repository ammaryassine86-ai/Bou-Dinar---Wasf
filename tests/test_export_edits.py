"""Lot 2, fix 1: what the director changes in the review editor while a film is being exported
is kept.

The export used to write back, at its very end, the copy of projet.json it had read at the
start: every edit, validation or withdrawn approval made in the meantime was lost."""
import copy
from pathlib import Path

from editeur_client import editor_client

from wasf import pipeline
from wasf.pipeline import RenderOptions, changed_during_export, render
from wasf.project import load_project, now_iso, save_project

DIRECTOR = "Réalisatrice A"


def _approve(path: Path) -> None:
    project = load_project(path)
    project.realisateur = DIRECTOR
    for seg in project.segments:
        seg.statut, seg.valide_par, seg.valide_le = "valide", DIRECTOR, now_iso()
    project.validation_realisateur, project.approuve_par = True, DIRECTOR
    save_project(project, path)


def _export_while(path: Path, monkeypatch, edit, brouillon: bool = False):
    """Export, calling `edit()` once the export has read the project: what a director does in
    the editor while the film is being voiced and mixed."""
    real_build_mix = pipeline.build_mix

    def build_mix(*args, **kwargs):
        edit()
        return real_build_mix(*args, **kwargs)

    monkeypatch.setattr(pipeline, "build_mix", build_mix)
    logs: list[str] = []
    outputs = render(path, RenderOptions(moteur="bip", annonce=False, brouillon=brouillon),
                     log=logs.append)
    return outputs, logs


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_a_text_edited_in_the_editor_during_the_export_is_kept(real_path, monkeypatch):
    _approve(real_path)
    client = editor_client(real_path)
    first = load_project(real_path).segments[0]
    new_text = "Un carré jaune glisse lentement vers la droite de l'écran."
    assert new_text != first.texte

    def edit():
        answer = client.post(f"/api/passage/{first.id}",
                             json={"action": "enregistrer", "texte": new_text})
        assert answer.status_code == 200

    outputs, logs = _export_while(real_path, monkeypatch, edit)
    after = load_project(real_path)
    seg = after.segment(first.id)
    assert seg.texte == new_text                         # the edit survived the export
    assert after.validation_realisateur is False         # and what it implies: approval withdrawn
    actions = [entry["action"] for entry in after.historique]
    assert "approbation_realisation_annulee" in actions  # the editor's own log lines are kept
    last = after.historique[-1]
    assert last["action"] == "export" and last["passages"] == len(after.segments)
    assert last["modifie_pendant_export"] == [f"{first.id} : texte modifié",
                                              "approbation de la réalisation retirée"]
    warnings = [line for line in logs if "modifiée pendant l'export" in line]
    assert len(warnings) == 1 and first.id in warnings[0] and "relancez" in warnings[0]
    # The film was made from the text read at the start, and the measurement says which text.
    assert seg.voix_mesuree["texte"] == first.texte
    vtt = _flat(outputs["sous_titres_vtt"].read_text(encoding="utf-8"))
    assert _flat(first.texte) in vtt and _flat(new_text) not in vtt
    # The other passages got this export's measurements as before.
    assert all(s.voix_mesuree.get("moteur") == "bip" for s in after.segments)
    assert after.energie["export"]["duree_s"] >= 0


def test_validations_made_during_a_working_export_are_kept(real_path, monkeypatch):
    project = load_project(real_path)
    project.realisateur = DIRECTOR                       # a signer, nothing validated yet
    save_project(project, real_path)
    client = editor_client(real_path)
    target = project.segments[-1]
    assert target.statut != "ignore"

    def edit():
        answer = client.post(f"/api/passage/{target.id}", json={"action": "ignorer"})
        assert answer.status_code == 200

    _outputs, logs = _export_while(real_path, monkeypatch, edit, brouillon=True)
    after = load_project(real_path)
    assert after.segment(target.id).statut == "ignore"
    assert after.segment(target.id).valide_par == DIRECTOR
    assert after.historique[-1]["modifie_pendant_export"] == [
        f"{target.id} : {target.statut} → ignore"]
    assert any("modifiée pendant l'export" in line for line in logs)


def test_an_export_with_no_edit_meanwhile_says_nothing(real_path, monkeypatch):
    _approve(real_path)
    before = load_project(real_path)
    _outputs, logs = _export_while(real_path, monkeypatch, lambda: None)
    after = load_project(real_path)
    assert "modifie_pendant_export" not in after.historique[-1]
    assert not any("modifiée pendant l'export" in line for line in logs)
    assert [s.texte for s in after.segments] == [s.texte for s in before.segments]
    assert after.validation_realisateur is True


def test_what_counts_as_a_change_during_an_export(real_path):
    _approve(real_path)
    before = load_project(real_path)
    assert changed_during_export(before, copy.deepcopy(before)) == []

    after = copy.deepcopy(before)
    after.segments[0].texte += " Ajout."
    after.segments[1].statut = "modifie"
    assert changed_during_export(before, after) == [
        f"{before.segments[0].id} : texte modifié",
        f"{before.segments[1].id} : valide → modifie"]

    after = copy.deepcopy(before)
    removed = after.segments.pop()
    after.validation_realisateur = False
    assert changed_during_export(before, after) == [f"{removed.id} : passage retiré",
                                                    "approbation de la réalisation retirée"]

    after = copy.deepcopy(before)                       # someone else signs one passage
    after.segments[0].valide_par = "Quelqu'un d'autre"
    assert changed_during_export(before, after) == [
        "signatures (la mention lue en tête du film change)"]

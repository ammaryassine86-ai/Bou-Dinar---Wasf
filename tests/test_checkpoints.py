"""T27 · The project is saved, atomically, after every passage. An interrupted run goes on with
--reprendre without asking the AI again for what is done; --refaire-echecs redoes only the
passages where the AI failed; meanwhile the editor and the export wait."""
import json
import os
from dataclasses import asdict

import pytest
from editeur_client import editor_client

from wasf import pipeline
from wasf import project as project_module
from wasf.agent import DescriberAgent, review_flags
from wasf.cli import main
from wasf.pipeline import (
    ProjectExistsError,
    RenderError,
    RenderOptions,
    ResumeError,
    prepare,
    render,
)
from wasf.project import load_project, save_project
from wasf.providers import MockProvider, ProviderError


class Counting(MockProvider):
    """Writes like the mock (deterministic), records which passage each call was for, and can
    fail on some passages or stop the run (Ctrl+C) at the n-th draft."""
    name = "essai"
    model = "doublure"

    def __init__(self, fail_on=(), interrupt_at=None):
        self.calls, self.current = [], None
        self.fail_on, self.interrupt_at = set(fail_on), interrupt_at

    def generate(self, system, user, images=None, meta=None):
        mode = (meta or {}).get("mode")
        self.calls.append((self.current, mode))
        drafts = sum(m == "brouillon" for _, m in self.calls)
        if mode == "brouillon" and self.interrupt_at == drafts:
            raise KeyboardInterrupt
        if mode == "brouillon" and self.current in self.fail_on:
            raise ProviderError("429 Too Many Requests: quota dépassé")
        return super().generate(system, user, images, meta)

    def asked_for(self):
        return sorted({seg for seg, mode in self.calls if mode == "brouillon"})


@pytest.fixture()
def run(demo_files, tmp_path, monkeypatch):
    """prepare() on the demo with a given Counting provider; same output folder every time."""
    original = DescriberAgent.describe

    def tracking(self, segment, *args, **kwargs):
        self.provider.current = segment.id
        return original(self, segment, *args, **kwargs)
    monkeypatch.setattr(DescriberAgent, "describe", tracking)
    logs = []

    def go(provider, **options):
        monkeypatch.setattr(pipeline, "get_provider", lambda *a, **k: provider)
        return prepare(demo_files["video"], demo_files["intention"],
                       sous_titres=demo_files["sous_titres"], sortie=tmp_path / "projet",
                       log=logs.append, **options)
    go.logs, go.path = logs, tmp_path / "projet" / "projet.json"
    return go


def _interrupted(run):
    with pytest.raises(KeyboardInterrupt):
        run(Counting(interrupt_at=3))
    return load_project(run.path)


def test_an_interrupted_run_keeps_every_finished_passage(run):
    project = _interrupted(run)
    assert project.preparation["etat"] == "en_cours"
    states = {s.id: s.etat_ia for s in project.segments}
    assert states == {"p001": "fait", "p002": "fait", "p003": "a_faire", "p004": "a_faire",
                      "p005": "a_faire"}
    assert all(s.brouillon_ia for s in project.segments[:2])
    assert not any(s.brouillon_ia for s in project.segments[2:])
    assert any("--reprendre" in line for line in run.logs)
    assert not list(run.path.parent.glob(".projet-*"))          # no half-written file around


def test_resume_never_asks_again_for_finished_passages(run, demo_files, tmp_path):
    before = _interrupted(run)
    done = {s.id: asdict(s) for s in before.segments if s.etat_ia == "fait"}
    provider = Counting()
    run(provider, reprendre=True)
    assert provider.asked_for() == ["p003", "p004", "p005"]
    assert not any(seg in done for seg, _ in provider.calls)    # no call at all for p001, p002
    after = load_project(run.path)
    assert after.preparation["etat"] == "terminee" and after.historique[-1]["action"] == "reprise"
    assert all(s.etat_ia == "fait" for s in after.segments)
    for seg in after.segments:
        if seg.id in done:
            assert asdict(seg) == done[seg.id]
    assert after.echantillon is not None
    # The same texts as a run that was never interrupted.
    whole = prepare(demo_files["video"], demo_files["intention"],
                    sous_titres=demo_files["sous_titres"], fournisseur="mock",
                    sortie=tmp_path / "entier", log=lambda _m: None)
    assert [s.brouillon_ia for s in after.segments] == \
        [s.brouillon_ia for s in load_project(whole).segments]


def test_redo_only_the_failed_passages(run):
    run(Counting(fail_on={"p002", "p004"}))
    project = load_project(run.path)
    assert [s.etat_ia for s in project.segments] == ["fait", "echec", "fait", "echec", "fait"]
    assert "rien de décrit" in review_flags(project.segment("p002"))
    untouched = {s.id: asdict(s) for s in project.segments if s.id not in ("p002", "p004")}
    # Meanwhile, someone writes p004 by hand in the editor: that one is theirs now.
    client = editor_client(run.path)
    assert client.post("/api/passage/p004", json={"action": "enregistrer",
                                                  "texte": "Un carré orange, seul."}).status_code == 200
    provider = Counting()
    run(provider, refaire_echecs=True)
    assert provider.asked_for() == ["p002"]
    after = load_project(run.path)
    assert after.segment("p002").etat_ia == "fait" and after.segment("p002").brouillon_ia
    assert after.segment("p004").texte == "Un carré orange, seul."
    assert after.historique[-1]["action"] == "refaire_echecs"
    for seg in after.segments:
        if seg.id in untouched:
            assert asdict(seg) == untouched[seg.id]
    assert any("p004" in line and "main" in line for line in run.logs)
    # Nothing left to redo: no call at all.
    again = Counting()
    run(again, refaire_echecs=True)
    assert again.calls == [] and any("Aucun passage à refaire" in line for line in run.logs)


def test_the_project_is_saved_after_every_passage(run, monkeypatch):
    seen = []
    original = pipeline.save_project

    def watching(project, path):
        result = original(project, path)
        on_disk = json.loads(path.read_text(encoding="utf-8"))   # whole, valid JSON each time
        seen.append(sum(s["etat_ia"] == "fait" for s in on_disk["segments"]))
        return result
    monkeypatch.setattr(pipeline, "save_project", watching)
    run(Counting())
    assert seen == [0, 1, 2, 3, 4, 5, 5]      # the plan, one per passage, the end


def test_saving_is_atomic_and_durable(tmp_path, monkeypatch, demo_files):
    path = prepare(demo_files["video"], demo_files["intention"], fournisseur="mock",
                   sous_titres=demo_files["sous_titres"], sortie=tmp_path / "p", log=lambda _m: None)
    good = path.read_bytes()
    project = load_project(path)
    project.film = "Changé"
    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(project_module.os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd)))
    save_project(project, path)
    assert len(synced) >= 1 and load_project(path).film == "Changé"
    good = path.read_bytes()
    for failure in (OSError("disque plein"), KeyboardInterrupt()):
        def broken(*_args, error=failure):
            raise error
        monkeypatch.setattr(project_module.os, "replace", broken)
        project.film = "Jamais écrit"
        with pytest.raises(type(failure)):
            save_project(project, path)
        assert path.read_bytes() == good                       # the previous file, whole
        assert not list(path.parent.glob(".projet-*"))         # no leftover temporary file


def test_editor_and_export_wait_until_drafting_is_over(run):
    _interrupted(run)
    client = editor_client(run.path)
    data = client.get("/api/projet").get_json()
    assert data["preparation_en_cours"] is True and data["echantillon"] == []
    for path, body in (("/api/passage/p001", {"action": "valider"}),
                       ("/api/projet", {"realisateur": "Réalisatrice A"}),
                       ("/api/valider-sans-alerte", {})):
        answer = client.post(path, json=body)
        assert answer.status_code == 409 and "--reprendre" in answer.get_json()["erreur"]
    for brouillon in (False, True):
        with pytest.raises(RenderError, match="--reprendre"):
            render(run.path, RenderOptions(moteur="bip", brouillon=brouillon, annonce=False))
    run(Counting(), reprendre=True)
    assert client.post("/api/projet", json={"realisateur": "Réalisatrice A"}).status_code == 200


def test_a_new_run_points_to_resume_instead_of_overwriting(run):
    _interrupted(run)
    with pytest.raises(ProjectExistsError, match="--reprendre"):
        run(Counting())


def test_missing_frames_are_extracted_again_without_any_ai_call(run):
    project = _interrupted(run)
    lost = [run.path.parent / rel for rel in project.segment("p004").images]
    for frame in lost:
        frame.unlink()
    provider = Counting()
    run(provider, reprendre=True)
    assert all(frame.exists() for frame in lost) and provider.asked_for() == ["p003", "p004", "p005"]


def test_projects_made_before_checkpoints(run):
    run(Counting(fail_on={"p003"}))
    project = load_project(run.path)
    project.preparation = {}
    for seg in project.segments:
        seg.etat_ia = ""                     # as saved by Wasf before this change
    save_project(project, run.path)
    with pytest.raises(ResumeError, match="Rien à reprendre"):
        run(Counting(), reprendre=True)
    provider = Counting()
    run(provider, refaire_echecs=True)       # the failure is still recognised
    assert provider.asked_for() == ["p003"]


def test_command_line(demo_files, tmp_path, monkeypatch, capsys):
    base = ["preparer", str(demo_files["video"]), "--intention", str(demo_files["intention"]),
            "--sous-titres", str(demo_files["sous_titres"]), "--fournisseur", "mock"]
    assert main(base + ["--sortie", str(tmp_path / "vide"), "--reprendre"]) == 1
    assert "Aucun projet" in capsys.readouterr().err
    assert main(base + ["--sortie", str(tmp_path / "x"), "--reprendre", "--remplacer"]) == 1
    assert "choisissez" in capsys.readouterr().err
    monkeypatch.setattr(pipeline, "get_provider", lambda *a, **k: Counting(interrupt_at=2))
    assert main(base + ["--sortie", str(tmp_path / "coupe")]) == 130
    out = capsys.readouterr()
    assert "--reprendre" in out.out and "Arrêté" in out.err
    monkeypatch.setattr(pipeline, "get_provider", lambda *a, **k: Counting())
    assert main(base + ["--sortie", str(tmp_path / "coupe"), "--reprendre"]) == 0
    assert load_project(tmp_path / "coupe" / "projet.json").preparation["etat"] == "terminee"

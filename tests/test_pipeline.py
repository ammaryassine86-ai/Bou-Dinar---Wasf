"""End to end: demo clip -> agent drafts -> human review in the editor -> export."""
import json

import pytest
from editeur_client import editor_client

from wasf import media
from wasf.pipeline import RenderError, RenderOptions, prepare, render
from wasf.project import load_project


@pytest.fixture()
def project_path(demo_files, tmp_path):
    return prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], sortie=tmp_path / "projet",
                   log=lambda _msg: None)


def test_prepare_drafts_fit_their_pauses(project_path):
    project = load_project(project_path)
    assert project.accord_producteur and project.fournisseur == "mock"
    assert len(project.segments) == 5
    for seg in project.segments:
        assert seg.brouillon_ia and len(seg.texte.split()) <= seg.budget_mots
        assert seg.journal_agent[0]["etape"] == "brouillon"
        assert all((project_path.parent / img).exists() for img in seg.images)
    assert "signal" not in project.segments[1].texte.lower()  # director's "avoid" list


def test_without_a_language_the_track_follows_the_dialogue(demo_files, tmp_path):
    lines = demo_files["intention"].read_text(encoding="utf-8").splitlines()
    unset = tmp_path / "sans_langue.yaml"
    unset.write_text("\n".join(line for line in lines if not line.startswith("langue:")),
                     encoding="utf-8")
    logs: list[str] = []
    path = prepare(demo_files["video"], unset, sous_titres=demo_files["sous_titres"],
                   sortie=tmp_path / "suit", log=logs.append)
    assert load_project(path).langue == "fr" and any("comme les dialogues" in m for m in logs)
    # The director's choice wins, with a warning when the dialogue is in another language.
    logs.clear()
    path = prepare(demo_files["video"], demo_files["intention"], langue="aeb",
                   sous_titres=demo_files["sous_titres"], sortie=tmp_path / "choisie",
                   log=logs.append)
    assert load_project(path).langue == "aeb"
    assert any("les dialogues semblent en français" in m for m in logs)


def test_agent_sees_the_story_so_far_but_not_what_comes_next(demo_files, tmp_path, monkeypatch):
    import wasf.pipeline as pipeline
    from wasf.gaps import parse_subtitles
    from wasf.providers import MockProvider

    prompts = []

    class Recorder(MockProvider):
        def generate(self, system, user, images=None, meta=None):
            if (meta or {}).get("mode") == "brouillon":
                prompts.append(user)
            return super().generate(system, user, images, meta)

    monkeypatch.setattr(pipeline, "get_provider", lambda *args, **kwargs: Recorder())
    path = prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], sortie=tmp_path / "recit",
                   log=lambda _msg: None)
    project = load_project(path)
    cues = parse_subtitles(demo_files["sous_titres"])
    third = prompts[2]  # the pause from 12 s to 18 s
    assert project.segments[1].texte in third  # an earlier description
    assert cues[0].text in third               # earlier dialogue, before the line "just before"
    assert cues[-1].text not in third          # nothing from later in the film


def test_review_then_export(real_path, tmp_path):
    project_path = real_path  # drafted by a stand-in for a real model (not a simulation)
    client = editor_client(project_path)
    data = client.get("/api/projet").get_json()
    first = data["segments"][0]["id"]

    # Nobody to sign (no director name, no describer): validation refused.
    client.post("/api/projet", json={"realisateur": ""})
    assert client.post(f"/api/passage/{first}", json={"action": "valider"}).status_code == 409
    # This test follows the optional describer path; the director path is tested below.
    client.post("/api/projet", json={"descripteur": "Sana Ben Ali", "realisateur": "Équipe Wasf"})

    # Over budget: refused, with the check explaining why.
    too_long = " ".join(["mot"] * 40)
    response = client.post(f"/api/passage/{first}", json={"action": "valider", "texte": too_long})
    assert response.status_code == 409 and "Trop long" in response.get_json()["erreur"]

    # Export refused while passages are pending.
    with pytest.raises(RenderError):
        render(project_path, RenderOptions(moteur="bip"))
    # Director approval refused while passages are pending.
    assert client.post("/api/projet", json={"validation_realisateur": True}).status_code == 409

    for seg in data["segments"]:
        text = seg["brouillon_ia"] if seg["id"] != first else "Un carré jaune."
        result = client.post(f"/api/passage/{seg['id']}", json={"action": "valider", "texte": text})
        assert result.status_code == 200, result.get_json()
    assert client.post("/api/projet", json={"validation_realisateur": True}).status_code == 200

    # Editing a validated passage withdraws the director's approval.
    client.post(f"/api/passage/{first}", json={"action": "rouvrir"})
    project = load_project(project_path)
    assert not project.validation_realisateur and project.segment(first).statut != "valide"
    client.post(f"/api/passage/{first}", json={"action": "valider", "texte": "Un carré jaune."})
    client.post("/api/projet", json={"validation_realisateur": True})

    outputs = render(project_path, RenderOptions(moteur="bip"), log=lambda _msg: None)
    film = outputs["film"]
    assert film.exists() and media.duration(film) >= 30.0 + 4.0 - 0.2  # film + disclosure card
    vtt = outputs["sous_titres_vtt"].read_text(encoding="utf-8")
    assert vtt.startswith("WEBVTT") and "écrite et validée par Sana Ben Ali" in vtt
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    assert report["passages"]["valides"] == 5 and report["droits"]["entrainement_sur_le_film"] is False
    assert report["passages"]["modifies_par_un_humain"] >= 0
    assert all(v["depassement_s"] <= 0.05 for v in report["voix"])
    assert (outputs["voix_seule"].stat().st_size > 1000)


def test_director_mode_flags_then_validates_the_rest_in_one_click(real_path):
    project_path = real_path  # drafted by a stand-in for a real model (not a simulation)
    client = editor_client(project_path)
    data = client.get("/api/projet").get_json()
    ids = [s["id"] for s in data["segments"]]
    flagged = [s["id"] for s in data["segments"] if s["signalements"]]
    # The demo's two 2-second pauses only fit 3 words: the AI is unsure, so they are flagged.
    # The one-click count leaves out the random sample, which is checked one by one first.
    assert flagged == ["p001", "p005"]
    assert data["sans_alerte"] == len(ids) - 2 - len(data["echantillon"])

    client.post("/api/projet", json={"realisateur": ""})
    assert client.post("/api/valider-sans-alerte").status_code == 409  # nobody to sign
    client.post("/api/projet", json={"realisateur": "Équipe Wasf"})
    # Never blind: a random sample of the clean passages is validated one by one first.
    blocked = client.post("/api/valider-sans-alerte")
    sample = blocked.get_json()["echantillon"]
    assert blocked.status_code == 409 and sample and not set(sample) & set(flagged)
    for seg_id in sample:
        assert client.post(f"/api/passage/{seg_id}", json={"action": "valider"}).status_code == 200
    result = client.post("/api/valider-sans-alerte").get_json()
    assert set(result["valides"]) == set(ids) - set(flagged) - set(sample)

    # Flagged passages are never validated in bulk: the director looks at each one.
    assert client.post("/api/projet", json={"validation_realisateur": True}).status_code == 409
    for seg_id in flagged:
        assert client.post(f"/api/passage/{seg_id}", json={"action": "valider"}).status_code == 200
    assert client.post("/api/projet", json={"validation_realisateur": True}).status_code == 200
    project = load_project(project_path)
    assert all(s.valide_par == "Équipe Wasf" for s in project.segments)
    assert [s.id for s in project.segments if s.valide_en_lot] == result["valides"]

    outputs = render(project_path, RenderOptions(moteur="bip", annonce=False),
                     log=lambda _msg: None)
    vtt = outputs["sous_titres_vtt"].read_text(encoding="utf-8")
    assert "écrite par intelligence artificielle, validée par Équipe Wasf" in vtt
    assert "Approuvée par la réalisation" in vtt
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    assert report["humains"]["mode"] == "realisation"
    assert report["passages"]["valides_en_un_clic"] == len(result["valides"])
    assert report["passages"]["echantillon_relu"] == len(sample)
    assert "validée par Équipe Wasf" in outputs["credits"].read_text(encoding="utf-8")


def test_draft_export_is_labelled(project_path, tmp_path):
    outputs = render(project_path, RenderOptions(moteur="bip", brouillon=True, annonce=False,
                                                 sortie=tmp_path / "brouillon"),
                     log=lambda _msg: None)
    assert "Version de travail" in outputs["credits"].read_text(encoding="utf-8") or \
        "non validée" in outputs["sous_titres_vtt"].read_text(encoding="utf-8")
    assert media.duration(outputs["film"]) == pytest.approx(30.0, abs=0.2)

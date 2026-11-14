"""Trust fixes: what Wasf tells the director and the audience must be true.

Each test here started as a failing case of the evaluation harness (run_eval.py).
"""
import json

import pytest

from wasf import pipeline
from wasf.agent import DescriberAgent, has_errors, review_flags, run_checks, validable_in_one_click
from editeur_client import editor_client
from wasf.export import label_text
from wasf.pipeline import RenderOptions, prepare, render
from wasf.project import Project, Segment, load_project
from wasf.prompts import parse_reply
from wasf.providers import Provider


class Scripted(Provider):
    """A stand-in model that returns the given reply (or reply(meta) when it is a function)."""

    name, model = "essai", "script"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def generate(self, system, user, images=None, meta=None):
        self.calls.append((meta or {}).get("mode"))
        return self.reply(meta or {}) if callable(self.reply) else self.reply


def J(description, confiance=0.9):
    return json.dumps({"description": description, "confiance": confiance}, ensure_ascii=False)


def drafted(reply, langue="fr", budget=12, previous=""):
    seg = Segment(id="p002", debut=0, fin=6, parole_debut=0.3, parole_fin=5.7, budget_mots=budget,
                  images=["a.jpg"])
    model = Scripted(reply)
    DescriberAgent(model, film="Test", langue=langue, log=quiet).describe(
        seg, [b"jpeg"], [], previous=previous)
    return seg, model.calls


def codes(checks):
    return {c["code"] for c in checks}


def sign_everything(client, path):
    """The director validates every passage one by one."""
    for seg in load_project(path).segments:
        response = client.post(f"/api/passage/{seg.id}", json={"action": "valider"})
        assert response.status_code == 200, response.get_json()


def quiet(_message):
    pass


# --------------------------------------------------------------------------- Q1 (T31, T32)
def test_the_notice_names_only_people_who_signed(real_path):
    client = editor_client(real_path)
    client.post("/api/projet", json={"realisateur": "Réalisatrice A"})
    sign_everything(client, real_path)
    assert client.post("/api/projet", json={"validation_realisateur": True}).status_code == 200
    assert load_project(real_path).approuve_par == "Réalisatrice A"

    # Another director's name typed after approval withdraws it; the notice keeps the real signer.
    response = client.post("/api/projet", json={"realisateur": "Personne B"}).get_json()
    assert "avis" in response
    project = load_project(real_path)
    assert not project.validation_realisateur and project.approuve_par == ""
    assert "Réalisatrice A" in label_text(project) and "Personne B" not in label_text(project)

    # A describer named after the director validated everything is not credited with the work.
    client.post("/api/projet", json={"descripteur": "Descripteur X"})
    assert client.post("/api/projet", json={"validation_realisateur": True}).status_code == 200
    label = label_text(load_project(real_path))
    assert label.startswith("Audiodescription écrite par intelligence artificielle, "
                            "validée par Réalisatrice A.")
    assert "Descripteur X" not in label
    out = render(real_path, RenderOptions(moteur="bip", annonce=False), log=quiet)
    credits = out["credits"].read_text(encoding="utf-8")
    assert "brouillons uniquement" not in credits and "validée par Réalisatrice A" in credits

    # Nobody approves without a director's name.
    client.post("/api/projet", json={"realisateur": ""})
    assert client.post("/api/projet", json={"validation_realisateur": True}).status_code == 409


def test_mixed_signatures_are_all_named():
    project = Project(film="F", video="v.mp4", duree=10.0, langue="fr", fournisseur="essai",
                      modele="m", realisateur="Rim", descripteur="Sana")
    project.segments = [
        Segment(id="p001", debut=0, fin=4, parole_debut=0.3, parole_fin=3.7, budget_mots=8,
                texte="Un carré.", statut="valide", valide_par="Sana"),
        Segment(id="p002", debut=5, fin=9, parole_debut=5.3, parole_fin=8.7, budget_mots=8,
                texte="Un rond.", statut="valide", valide_par="Rim")]
    assert label_text(project) == ("Audiodescription écrite par intelligence artificielle, "
                                   "validée par Sana et Rim.")
    project.segments[1].valide_par = "Sana"  # the describer signed everything
    assert label_text(project) == ("Audiodescription assistée par intelligence artificielle, "
                                   "écrite et validée par Sana.")


# --------------------------------------------------------------------------- Q3 (T10)
def test_a_simulation_is_announced_as_one(demo_files, tmp_path):
    path = prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], sortie=tmp_path / "simulation",
                   log=quiet)  # the offline mock
    client = editor_client(path)
    assert client.get("/api/projet").get_json()["simulation"] is True
    client.post("/api/projet", json={"realisateur": "Réalisatrice A"})
    sign_everything(client, path)
    assert client.post("/api/projet", json={"validation_realisateur": True}).status_code == 200
    out = render(path, RenderOptions(moteur="bip", annonce=False), log=quiet)
    vtt = out["sous_titres_vtt"].read_text(encoding="utf-8")
    assert "Simulation : aucune image n'a été analysée" in vtt
    assert "écrite par intelligence artificielle" not in vtt
    assert json.loads(out["rapport"].read_text(encoding="utf-8"))["simulation"] is True
    assert "simulation" in out["credits"].read_text(encoding="utf-8").lower()


def test_the_command_line_asks_which_model(tmp_path, capsys):
    from wasf.cli import _parser, main
    with pytest.raises(SystemExit):
        _parser().parse_args(["preparer", "film.mp4", "--intention", "i.yaml"])
    capsys.readouterr()
    args = _parser().parse_args(["preparer", "film.mp4", "--intention", "i.yaml",
                                 "--fournisseur", "mock"])
    assert args.fournisseur == "mock"
    assert main(["demo", str(tmp_path / "demo")]) == 0
    assert "--fournisseur mock" in capsys.readouterr().out  # the suggested next step says it


# --------------------------------------------------------------------------- Q2 (T28)
def test_preparer_never_overwrites_a_review(real_path, demo_files, capsys):
    from wasf.cli import main
    from wasf.pipeline import ProjectExistsError
    client = editor_client(real_path)
    client.post("/api/projet", json={"realisateur": "Réalisatrice A"})
    sign_everything(client, real_path)
    out_dir = real_path.parent
    args = dict(sous_titres=demo_files["sous_titres"], sortie=out_dir, log=quiet)

    with pytest.raises(ProjectExistsError, match="5 passage"):
        prepare(demo_files["video"], demo_files["intention"], **args)
    assert all(s.statut == "valide" for s in load_project(real_path).segments)  # untouched
    command = ["preparer", str(demo_files["video"]), "--intention", str(demo_files["intention"]),
               "--sous-titres", str(demo_files["sous_titres"]), "--sortie", str(out_dir),
               "--fournisseur", "mock"]
    assert main(command) == 1 and "--remplacer" in capsys.readouterr().err

    path = prepare(demo_files["video"], demo_files["intention"], remplacer=True, **args)
    assert not any(s.statut == "valide" for s in load_project(path).segments)  # a fresh project
    backups = list(out_dir.glob("sauvegarde-*"))
    assert len(backups) == 1
    kept = load_project(backups[0] / "projet.json")
    assert all(s.statut == "valide" for s in kept.segments)  # the review is kept...
    assert (backups[0] / kept.video).resolve() == demo_files["video"].resolve()  # ...and opens
    assert (backups[0] / "images" / "p001_1.jpg").exists()


# --------------------------------------------------------------------------- Q4 (T17 to T20, T22)
def test_confidence_scales_and_text_after_the_json():
    def conf(raw):
        return parse_reply('{"description": "Amel sort.", "confiance": ' + raw + "}")["confiance"]
    assert conf("30") == pytest.approx(0.30)       # a percentage, not full confidence
    assert conf('"85 %"') == pytest.approx(0.85)
    assert conf('"0,3"') == pytest.approx(0.3)     # French decimal comma
    assert conf("1") == 1.0 and conf("0.8") == pytest.approx(0.8)
    assert conf("150") is None and conf("-1") is None and conf('"sûre"') is None  # unknown: flagged
    reply = parse_reply('{"description": "Amel sort.", "confiance": 0.9}\nNote : {aucune}')
    assert reply["description"] == "Amel sort." and reply["confiance"] == 0.9


def test_refusals_are_blocked_and_never_rewritten_blind():
    seg, calls = drafted(J("Désolé, je ne peux pas décrire cette image."))
    assert calls == ["brouillon"]  # a text-only rewrite would invent what the model refused to see
    assert "refus" in codes(seg.verifications) and not validable_in_one_click(seg)
    for text, langue in (("ما نجمش نوصف التصويرة هاذي.", "aeb"), ("لا أستطيع وصف هذه الصورة.", "ar"),
                         ("I'm sorry, I can't describe this image.", "fr")):
        assert "refus" in codes(run_checks(text, budget=20, avoid=[], dialogue="", langue=langue))


def test_wrong_script_or_language_is_sent_back_for_rewriting():
    replies = iter([J("Amel pose le téléphone sur la table."), J("أمل تحط البورتابل على الطاولة.")])
    seg, calls = drafted(lambda meta: next(replies), langue="aeb")
    assert calls == ["brouillon", "revision"] and seg.texte.startswith("أمل")
    assert not has_errors(seg.verifications)
    english = run_checks("Amel puts the phone on the table.", budget=12, avoid=[], dialogue="",
                         langue="fr")
    assert "ecriture" in codes(english)
    french = run_checks("Amel pose le téléphone sur la table, puis regarde la porte.", budget=12,
                        avoid=[], dialogue="", langue="fr")
    assert not has_errors(french)


def test_standard_arabic_in_a_derja_track_is_flagged():
    msa = run_checks("تضع أمل الهاتف على الطاولة وتنظر إلى الباب.", budget=12, avoid=[],
                     dialogue="", langue="aeb")
    assert "arabe_standard" in codes(msa) and not has_errors(msa)  # a warning: the director decides
    seg, _ = drafted(J("تضع أمل الهاتف على الطاولة وتنظر إلى الباب."), langue="aeb")
    assert "arabe standard probable" in review_flags(seg)
    derja = run_checks("أمل تحط البورتابل على الطاولة وتخزر للباب.", budget=12, avoid=[],
                       dialogue="", langue="aeb")
    assert "arabe_standard" not in codes(derja)


def test_a_passage_repeating_the_previous_one_is_flagged(demo_files, tmp_path, monkeypatch):
    seg, _ = drafted(J("Le carré bouge."), budget=8, previous="Le carré bouge.")
    assert "répète le passage précédent" in review_flags(seg) and not validable_in_one_click(seg)
    monkeypatch.setattr(pipeline, "get_provider", lambda *a, **k: Scripted(J("Le carré bouge.")))
    path = prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], sortie=tmp_path / "repetes", log=quiet)
    assert [s.id for s in load_project(path).segments if validable_in_one_click(s)] == ["p001"]
    client = editor_client(path)  # the editor's re-check keeps the flag
    response = client.post("/api/passage/p003", json={"action": "enregistrer",
                                                      "texte": "Le carré bouge."}).get_json()
    assert "répète le passage précédent" in response["passage"]["signalements"]


# --------------------------------------------------------------------------- Q5 (T13)
@pytest.mark.parametrize("avoid, text, caught", [
    ("le visiteur", "Un visiteur entre.", True),            # another article
    ("visiteur", "La visiteuse entre.", True),              # feminine
    ("visiteur", "Deux visiteurs entrent.", True),          # plural
    ("signal", "Les signaux clignotent.", True),            # plural in -aux
    ("départ", "Le depart approche.", True),                # accent dropped
    ("Lettres", "elle pose la lettre", True),               # case and number
    ("la lettre d'amour", "Elle cache une lettre d’amour.", True),  # a phrase, curly apostrophe
    ("الإشارة", "تظهر اشارة خضراء.", True),                  # no hamza, no article
    ("رسالة", "أمل تقرا الرسالة.", True),                    # with the article
    ("الرسالة", "أمل تقرا رساله.", True),                    # ta marbuta written ه
    ("lettre", "Elle lit la missive.", False),              # a synonym: the director lists it
    ("port", "Elle ouvre la porte.", False),                # a different word: no false alarm
])
def test_the_avoid_list_survives_spelling(avoid, text, caught):
    checks = run_checks(text, budget=20, avoid=[avoid], dialogue="", langue="fr")
    assert ("a_eviter" in codes(checks)) is caught


# --------------------------------------------------------------------------- Q6
def test_sample_size():
    from wasf.agent import sample_size
    # 10 % of the clean passages, rounded up; at least 3 once there are 10 or more.
    assert [sample_size(n) for n in (0, 1, 3, 9, 10, 29, 31, 150)] == [0, 1, 1, 1, 3, 3, 4, 15]


def test_one_click_needs_a_random_sample_first(real_path):
    client = editor_client(real_path)
    client.post("/api/projet", json={"realisateur": "Réalisatrice A"})
    data = client.get("/api/projet").get_json()
    sample = data["echantillon"]
    clean = [s["id"] for s in data["segments"] if not s["signalements"]]
    assert len(sample) == 1 and set(sample) <= set(clean)  # 10 % of 3 clean passages, rounded up
    assert data["sans_alerte"] == len(clean) - 1
    blocked = client.post("/api/valider-sans-alerte")
    assert blocked.status_code == 409 and blocked.get_json()["echantillon"] == sample
    for seg_id in sample:
        assert client.post(f"/api/passage/{seg_id}", json={"action": "valider"}).status_code == 200
    done = client.post("/api/valider-sans-alerte").get_json()["valides"]
    assert set(done) == set(clean) - set(sample)

    sign_everything_left(client)
    assert client.post("/api/projet", json={"validation_realisateur": True}).status_code == 200
    out = render(real_path, RenderOptions(moteur="bip", annonce=False), log=quiet)
    passages = json.loads(out["rapport"].read_text(encoding="utf-8"))["passages"]
    assert passages["echantillon_relu"] == 1 and passages["valides_en_un_clic"] == len(done)
    assert "échantillon" in out["credits"].read_text(encoding="utf-8")


def test_projects_made_before_the_sample_get_one(real_path):
    project = load_project(real_path)
    project.echantillon = []
    from wasf.project import save_project
    save_project(project, real_path)
    data = editor_client(real_path).get("/api/projet").get_json()
    assert len(data["echantillon"]) == 1 and load_project(real_path).echantillon == data["echantillon"]


# --------------------------------------------------------------------------- Q10
def test_the_report_names_the_model_that_answered(demo_files, tmp_path, monkeypatch):
    class Routed(Scripted):
        """Asked for one model, answered by another, as when a provider reroutes a retired name."""

        def generate(self, system, user, images=None, meta=None):
            self._saw("gemini-3.6-flash")
            return super().generate(system, user, images, meta)

    model = Routed(J("Plan fixe."))
    model.model = "gemini-3.5-flash"
    monkeypatch.setattr(pipeline, "get_provider", lambda *a, **k: model)
    path = prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], sortie=tmp_path / "modeles", log=quiet)
    assert load_project(path).modeles_utilises == ["gemini-3.6-flash"]
    client = editor_client(path)
    client.post("/api/projet", json={"realisateur": "Réalisatrice A"})
    sign_everything_left(client)
    client.post("/api/projet", json={"validation_realisateur": True})
    out = render(path, RenderOptions(moteur="bip", annonce=False), log=quiet)
    assert json.loads(out["rapport"].read_text(encoding="utf-8"))["ia"]["modeles_utilises"] == [
        "gemini-3.6-flash"]
    assert "modèle gemini-3.6-flash" in out["credits"].read_text(encoding="utf-8")


def sign_everything_left(client):
    for seg in client.get("/api/projet").get_json()["segments"]:
        if seg["statut"] not in ("valide", "ignore"):
            assert client.post(f"/api/passage/{seg['id']}", json={"action": "valider"}).status_code == 200

"""The fixes to the known limits: frames where the image changes, the optional second look,
gestures said in other words, a shorter prompt.

The frame choice is tested for real, on a video FFmpeg makes. Model replies are scripted.
"""
import json
import subprocess

import numpy as np
import pytest
from editeur_client import editor_client

from wasf import media
from wasf.agent import DescriberAgent, review_flags, run_checks
from wasf.emotions import check_evidence
from wasf.export import transparency_report
from wasf.pipeline import _moments, prepare
from wasf.project import Project, Segment, save_project
from wasf.prompts import DRAFT_JSON, SYSTEM_PROMPT, parse_second_look
from wasf.providers import MockProvider, Provider


def codes(checks):
    return {c["code"] for c in checks}


def make_clip(path, flash=None):
    """10 s of grey; with flash=(a, b), a white box shows only between a and b seconds."""
    box = (f",drawbox=x=100:y=50:w=120:h=80:color=white:t=fill:enable='between(t,{flash[0]},"
           f"{flash[1]})'" if flash else "")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=gray:s=320x180:d=10:r=25{box}", "-pix_fmt", "yuv420p", str(path)],
                   check=True)
    return path


# --------------------------------------------------------------------------- frame choice
def test_a_brief_gesture_between_evenly_spaced_frames_is_caught(tmp_path):
    video = make_clip(tmp_path / "flash.mp4", flash=(5.2, 5.6))
    even = [6.0, 7.0]                      # what evenly spaced frames would show: no box
    picked = _moments(video, 5.0, 8.0, 2, even, adaptive=True)
    assert len(picked) == 2 and picked == sorted(picked)
    assert any(5.2 <= t <= 5.6 for t in picked)
    frame = media.extract_frame(video, next(t for t in picked if 5.2 <= t <= 5.6),
                                tmp_path / "seen.jpg")
    still = media.extract_frame(video, 7.0, tmp_path / "even.jpg")
    assert frame.stat().st_size != still.stat().st_size      # the box is in the picked frame
    assert _moments(video, 5.0, 8.0, 2, even, adaptive=False) == even


def test_a_still_shot_keeps_the_evenly_spaced_frames(tmp_path):
    video = make_clip(tmp_path / "still.mp4")
    assert _moments(video, 2.0, 5.0, 2, [3.0, 4.0], adaptive=True) == [3.0, 4.0]


def test_past_the_end_of_the_video_nothing_breaks(tmp_path):
    video = make_clip(tmp_path / "short.mp4")
    assert _moments(video, 30.0, 33.0, 2, [31.0, 32.0], adaptive=True) == [31.0, 32.0]


def test_most_distinct_picks_the_odd_frame_out():
    plain = np.full((36, 64), 128, dtype=np.uint8)
    odd = plain.copy()
    odd[10:20, 20:32] = 250                                      # something appears, locally
    frames = [(float(i), plain.ravel()) for i in range(6)]
    frames[3] = (3.0, odd.ravel())
    assert 3.0 in media.most_distinct(frames, 2)
    assert media.most_distinct(frames[:2], 2) is None             # too few to choose from
    brighter = [(float(i), np.full(64 * 36, 100 + 20 * i, dtype=np.uint8)) for i in range(6)]
    assert media.most_distinct(brighter, 2) is None               # a fade is not a gesture


def test_both_ways_of_choosing_frames_work_end_to_end(demo_files, tmp_path):
    for choice in ("auto", "fixe"):
        path = prepare(demo_files["video"], demo_files["intention"],
                       sous_titres=demo_files["sous_titres"], fournisseur="mock",
                       sortie=tmp_path / choice, choix_images=choice, log=lambda _m: None)
        project = json.loads(path.read_text(encoding="utf-8"))
        assert project["historique"][-1]["choix_images"] == choice
        for seg in project["segments"]:
            assert seg["instants"] == sorted(seg["instants"])
            assert all(seg["debut"] - 3.0 - 1e-6 <= t <= seg["fin"] for t in seg["instants"])


# --------------------------------------------------------------------------- second look
class ByMode(Provider):
    """A stand-in model that answers by request kind and records what it was sent."""

    name, model = "essai", "script"

    def __init__(self, draft, verdicts=None, fail_second_look=False):
        self.draft, self.verdicts, self.fail = draft, verdicts, fail_second_look
        self.calls = []

    def generate(self, system, user, images=None, meta=None):
        mode = (meta or {}).get("mode")
        self.calls.append((mode, user, images))
        if mode == "verification":
            if self.fail:
                raise RuntimeError("délai dépassé")
            return json.dumps({"verifications": self.verdicts}, ensure_ascii=False)
        return json.dumps(self.draft, ensure_ascii=False)


DRAFT = {"observations": ["Karim serre les poings", "Leïla recule d'un pas"],
         "changements": [], "interactions": [{"qui": "Leïla", "envers": "Karim",
                                              "geste": "recule"}],
         "emotions": [], "description": "Karim serre les poings ; Leïla recule d'un pas.",
         "confiance": 0.9}


def describe(model, second_look=True):
    seg = Segment(id="p001", debut=10, fin=15, parole_debut=10.3, parole_fin=14.7,
                  budget_mots=20, images=["a.jpg", "b.jpg"], instants=[11.0, 13.0])
    DescriberAgent(model, film="F", langue="fr", personnages=[{"nom": "Karim"}, {"nom": "Leïla"}],
                   second_look=second_look, log=lambda _m: None).describe(seg, [b"a", b"b"], [])
    return seg


def test_a_claim_rejected_on_a_second_look_is_flagged():
    model = ByMode(DRAFT, [{"affirmation": "Karim serre les poings", "visible": "non"},
                           {"affirmation": "Leïla recule d'un pas", "visible": "oui"},
                           {"affirmation": "Leïla envers Karim : recule", "visible": "oui"}])
    seg = describe(model)
    mode, prompt, images = model.calls[-1]
    assert mode == "verification" and images == [b"a", b"b"]       # the same images, once more
    assert "1. Karim serre les poings" in prompt and "Leïla envers Karim : recule" in prompt
    assert [r["visible"] for r in seg.seconde_lecture] == ["non", "oui", "oui"]
    assert "non confirmé à la seconde lecture" in review_flags(seg)
    assert seg.texte == DRAFT["description"]                        # the AI never rewrites it here


def test_the_flag_survives_the_editor_and_leaves_with_the_claim(demo_files, tmp_path):
    seg = describe(ByMode(DRAFT, [{"affirmation": "Karim serre les poings", "visible": "non"}]))
    project = Project(film="F", video="f.mp4", duree=20, langue="fr", fournisseur="essai",
                      modele="m", personnages=[{"nom": "Karim"}, {"nom": "Leïla"}], segments=[seg])
    save_project(project, tmp_path / "projet.json")
    client = editor_client(tmp_path / "projet.json")
    client.post("/api/projet", json={"realisateur": "Nour"})
    kept = client.post("/api/passage/p001", json={"action": "enregistrer",
                                                  "texte": seg.texte}).get_json()["passage"]
    assert "signe_non_confirme" in codes(kept["verifications"])
    report = transparency_report(project, [], False)["seconde_lecture"]
    assert report == {"par": "aucune", "passages_relus": 1, "affirmations_non_confirmees": 1}


def test_the_second_look_only_runs_when_asked_and_useful():
    model = ByMode(DRAFT, [])
    describe(model, second_look=False)
    assert [m for m, _u, _i in model.calls] == ["brouillon"]
    scenery = dict(DRAFT, observations=["Une voiture passe dans la rue"], interactions=[],
                   description="Une voiture passe dans la rue.")
    model = ByMode(scenery, [])
    describe(model)
    assert [m for m, _u, _i in model.calls] == ["brouillon"]           # nobody to check
    seg = Segment(id="p002", debut=0, fin=5, parole_debut=0.3, parole_fin=4.7, budget_mots=20,
                  images=["a.jpg"])
    mock = MockProvider()
    DescriberAgent(mock, film="F", langue="fr", second_look=True,
                   log=lambda _m: None).describe(seg, [b"a"], [])
    assert seg.seconde_lecture == []                                   # a simulation: no look


def test_a_failed_second_look_keeps_the_passage():
    seg = describe(ByMode(DRAFT, fail_second_look=True))
    assert seg.texte == DRAFT["description"] and seg.seconde_lecture == []
    assert any(step.get("erreur") == "délai dépassé" for step in seg.journal_agent)


def test_second_look_replies_are_read_carefully():
    assert parse_second_look('{"verifications": [{"affirmation": "A", "visible": "Oui"}, '
                             '{"affirmation": "B", "visible": "peut-être"}, {"visible": "non"}, 3]}'
                             ) == [{"affirmation": "A", "visible": "oui"},
                                   {"affirmation": "B", "visible": "incertain"}]
    assert parse_second_look("pas de JSON") == []


# --------------------------------------------------------------------------- paraphrase
@pytest.mark.parametrize("text, seen", [
    ("Karim montre la porte du doigt et la regarde.", ["Karim pointe vers la porte"]),
    ("Leïla sourit et baisse la tête.", ["Leïla rit doucement"]),
    ("Elle s'éloigne et croise les bras.", ["Elle recule"]),
])
def test_the_same_gesture_in_other_words_is_not_taken_for_an_invention(text, seen):
    assert "signe_non_observe" not in codes(check_evidence(text, langue="fr", observations=seen))


def test_an_unrelated_gesture_is_still_caught():
    assert "signe_non_observe" in codes(check_evidence("Leïla pleure et serre les poings.",
                                                       langue="fr",
                                                       observations=["Une voiture passe"]))


# --------------------------------------------------------------------------- prompt
def test_the_prompt_is_shorter_and_keeps_every_rule():
    assert len(SYSTEM_PROMPT) < 2500 and len(DRAFT_JSON) < 160
    for rule in ("évite le regard", "toutes les lectures possibles", "jamais un acteur",
                 "sans nom", "diagnostic", "sans importance", '"changements"'):
        assert rule in SYSTEM_PROMPT


def test_run_checks_passes_the_second_look_on():
    checks = run_checks("Karim serre les poings.", budget=10, avoid=[], dialogue="", langue="fr",
                        names=["Karim"],
                        evidence={"observations": ["Karim serre les poings"],
                                  "non_confirmes": ["Karim serre les poings"]})
    assert "signe_non_confirme" in codes(checks)


# --------------------------------------------------------------------------- camera moves
def test_a_camera_pan_no_longer_hides_a_small_gesture(tmp_path):
    """A textured shot pans steadily; a small box flashes for 0.3 s mid-pan."""
    texture = tmp_path / "texture.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=640x180:d=1",
                    "-frames:v", "1", str(texture)], check=True)
    video = tmp_path / "pan.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(texture), "-t", "10",
                    "-r", "25", "-vf", ("crop=320:180:x='t*20':y=0,drawbox=x=140:y=70:w=30:h=30:"
                                        "color=white:t=fill:enable='between(t,6.6,6.9)'"),
                    "-pix_fmt", "yuv420p",
                    str(video)], check=True)
    thumbs = media.thumbnails(video, 5.0, 3.0, 6)
    with_pan_undone = media.most_distinct(thumbs, 2, align=True)
    as_before = media.most_distinct(thumbs, 2, align=False)
    assert any(6.6 <= t <= 6.9 for t in with_pan_undone)          # the flash is kept
    assert not any(6.6 <= t <= 6.9 for t in as_before)            # pixels alone keep the pan
    first, last = thumbs[0][1], thumbs[-1][1]
    assert media.change_score(first, last) * 5 < media.change_score(first, last, align=False)


# --------------------------------------------------------------------------- another model
def test_the_second_look_can_be_taken_by_another_provider(demo_files, tmp_path, monkeypatch):
    from wasf import pipeline
    writer = ByMode(dict(DRAFT, description="Une main se lève.",
                         observations=["Une main se lève"], interactions=[]))
    writer.name, writer.model = "gemini", "gemini-test"
    reader = ByMode({}, [{"affirmation": "Une main se lève", "visible": "non"}])
    reader.name, reader.model = "openai", "gpt-test"
    monkeypatch.setattr(pipeline, "get_provider",
                        lambda name, *args, **kwargs: reader if name == "openai" else writer)
    writer._saw("gemini-test")
    reader._saw("gpt-test")
    path = prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], fournisseur="gemini",
                   seconde_lecture="openai", sortie=tmp_path / "p", log=lambda _m: None)
    project = json.loads(path.read_text(encoding="utf-8"))
    assert {m for m, _u, _i in writer.calls} <= {"brouillon", "revision"}
    assert {m for m, _u, _i in reader.calls} == {"verification"}
    assert project["seconde_lecture"] == "openai (gpt-test)"
    assert set(project["modeles_utilises"]) == {"gemini-test", "gpt-test"}


def test_the_command_line_offers_the_choice():
    from wasf.cli import _parser
    base = ["preparer", "film.mp4", "--intention", "i.yaml", "--fournisseur", "mock"]
    assert _parser().parse_args(base).seconde_lecture is None
    assert _parser().parse_args(base + ["--seconde-lecture"]).seconde_lecture == "meme"
    assert _parser().parse_args(base + ["--seconde-lecture", "openai"]).seconde_lecture == "openai"
    with pytest.raises(SystemExit):
        _parser().parse_args(base + ["--seconde-lecture", "film2.mp4"])


# --------------------------------------------------------------------------- sentence supports
def supported(text, supports, observations, unconfirmed=(), langue="fr"):
    return codes(check_evidence(text, langue=langue, observations=observations,
                                supports=supports, unconfirmed=list(unconfirmed)))


def test_a_sentence_the_model_says_rests_on_nothing_is_flagged():
    seen = ["Karim serre les poings", "Leïla recule"]
    assert "phrase_sans_appui" not in supported("Karim serre les poings. Leïla recule.",
                                                [[1], [2]], seen)
    assert "phrase_sans_appui" in supported("Karim serre les poings. Il pleut.", [[1], []], seen)
    assert "phrase_sans_appui" in supported("Karim serre les poings.", [[7]], seen)   # no such one


def test_a_rejected_observation_flags_its_sentence_in_any_wording_and_language():
    seen = ["كريم يقبض يديه"]
    assert "signe_non_confirme" in supported("كريم متغشش برشا.", [[1]], seen,
                                             unconfirmed=seen, langue="aeb")
    assert "signe_non_confirme" not in supported("كريم متغشش برشا.", [[1]], seen, langue="aeb")


def test_a_rewrite_brings_its_own_supports():
    seg = Segment(id="p001", debut=0, fin=6, parole_debut=0.3, parole_fin=5.7, budget_mots=12,
                  images=["a.jpg"])

    class Rewriter(ByMode):
        def generate(self, system, user, images=None, meta=None):
            if (meta or {}).get("mode") == "revision":
                self.calls.append(("revision", user, images))
                return json.dumps({"description": "Karim serre les poings, l'air furieux.",
                                   "appuis": [[1]], "confiance": 0.8}, ensure_ascii=False)
            return super().generate(system, user, images, meta)

    model = Rewriter({"observations": ["Karim serre les poings"], "emotions": [],
                      "changements": [], "interactions": [], "appuis": [[1]],
                      "description": "Karim est clairement furieux.", "confiance": 0.8})
    DescriberAgent(model, film="F", langue="fr", personnages=[{"nom": "Karim"}],
                   log=lambda _m: None).describe(seg, [b"a"], [])
    assert seg.appuis_ia == [[1]] and 'Ajoute "appuis"' in model.calls[-1][1]
    assert "1. Karim serre les poings" in model.calls[-1][1]

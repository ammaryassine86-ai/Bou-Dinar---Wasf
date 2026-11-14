"""Faces, gestures and body language: the checks, the prompt, the reply, the frames, the editor.

Model replies here are scripted. These tests check what Wasf does with a reply, never whether a
model reads a face correctly: that needs a real model and real footage (docs/TESTS_EMOTIONS.md).
"""
import json

import pytest
from editeur_client import editor_client

from wasf import media, pipeline
from wasf.agent import (
    DescriberAgent,
    has_errors,
    review_flags,
    run_checks,
    validable_in_one_click,
)
from wasf.emotions import check_evidence, named_emotions
from wasf.export import transparency_report
from wasf.intent import IntentError, load_intent
from wasf.pipeline import prepare
from wasf.project import Project, Segment, load_project, save_project
from wasf.prompts import SYSTEM_PROMPT, build_draft_prompt, parse_reply
from wasf.providers import Provider


def codes(checks):
    return {c["code"] for c in checks}


def check(text, **kwargs):
    options = {"budget": 30, "avoid": [], "dialogue": "", "langue": "fr", **kwargs}
    return run_checks(text, **options)


def quiet(_message):
    pass


class Script(Provider):
    """A stand-in model: returns the scripted replies in turn and keeps what it was sent."""

    name, model = "essai", "script"

    def __init__(self, *replies):
        self.replies, self.prompts, self.images = list(replies), [], []

    def generate(self, system, user, images=None, meta=None):
        self.prompts.append(user)
        self.images.append(images)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return json.dumps(reply, ensure_ascii=False) if isinstance(reply, dict) else reply


# --------------------------------------------------------------------------- the checks
@pytest.mark.parametrize("text", [
    "Leïla baisse la tête, évite son regard et serre ses mains.",
    "Karim fronce les sourcils et serre les poings, l'air frustré.",
    "Leïla sourit, mais ses mains tremblent autour de sa tasse.",
    "Karim montre la porte du doigt.",
])
def test_visible_signs_and_supported_nuances_raise_nothing(text):
    assert codes(check(text)) == {"ok"}


@pytest.mark.parametrize("text, code", [
    ("Elle est clairement déprimée.", "diagnostic"),
    ("Karim est sans aucun doute furieux.", "certitude"),
    ("De toute évidence, Leïla est terrifiée.", "certitude"),
])
def test_certainty_and_labels_block_the_ai_text_but_only_warn_on_a_person(text, code):
    ai = check(text)
    assert code in codes(ai) and has_errors(ai)
    person = check(text, ai_text=False)
    assert code in codes(person) and not has_errors(person)


def test_an_emotion_without_a_visible_sign_is_flagged():
    checks = check("Leïla est inquiète.")
    flagged = [c for c in checks if c["code"] == "interpretation"]
    assert flagged and "sans signe visible" in flagged[0]["message"] and not has_errors(checks)


def test_the_signes_mode_keeps_the_earlier_strict_rule():
    text = "Karim fronce les sourcils, l'air frustré."
    assert codes(check(text, emotions_mode="nuancees")) == {"ok"}
    strict = check(text, emotions_mode="signes")
    assert "interpretation" in codes(strict) and "frustré" in strict[-1]["message"]


def test_an_unsure_emotion_stated_flatly_is_flagged():
    text = "Karim serre les poings, furieux."
    assert codes(check(text, emotions=[{"emotion": "colère", "certitude": 0.8}])) == {"ok"}
    unsure = check(text, emotions=[{"emotion": "colère", "certitude": 0.3}])
    assert "emotion_incertaine" in codes(unsure) and "30 %" in unsure[-1]["message"]
    hedged = check("Karim serre les poings, l'air furieux.",
                   emotions=[{"emotion": "colère", "certitude": 0.3}])
    assert "emotion_incertaine" not in codes(hedged)


def test_an_emotion_the_dialogue_already_says_is_flagged():
    checks = check("Karim serre les poings, l'air furieux.", dialogue="Je suis furieux !")
    assert "emotion_dialogue" in codes(checks)


def test_a_gesture_described_again_is_flagged():
    previous = "Karim croise les bras et fronce les sourcils."
    again = check("Près de la fenêtre, Karim croise toujours les bras et fronce les sourcils.",
                  previous=previous)
    assert "geste_repete" in codes(again)
    changed = check("Karim décroise les bras et sourit.", previous=previous)
    assert "geste_repete" not in codes(changed)


def test_character_names_are_not_emotions():
    assert "interpretation" in codes(check("سعيد يفتح الباب.", langue="ar"))
    assert codes(check("سعيد يفتح الباب.", langue="ar", names=["سعيد"])) == {"ok"}


def test_arabic_and_derja():
    assert codes(check("يبدو غاضبا وهو يقبض يديه.", langue="ar")) == {"ok"}
    assert "diagnostic" in codes(check("هي مكتئبة.", langue="ar"))
    assert "interpretation" in codes(check("أمل حزينة برشا.", langue="aeb"))


# Words from the native-speaker review of the Derja lists.
def test_derja_emotion_words_from_the_review():
    for text in ("سامي مكرز.", "أمل مكرزة.", "سامي منرفز.", "أمل منرفزة.", "أمل مكرّزة.",
                 "الصغار المنرفزين يجريو."):
        assert named_emotions(text, "aeb"), text
    assert "interpretation" in codes(check("أمل منرفزة برشا.", langue="aeb"))
    assert codes(check("أمل تبان منرفزة وهي تهز يديها.", langue="aeb")) == {"ok"}


def test_derja_ways_to_say_it_seems():
    unsure = [{"qui": "سامي", "emotion": "مكرز", "certitude": 0.3}]
    assert "emotion_incertaine" in codes(check("سامي مكرز، يديه مكتفين.", langue="aeb",
                                               emotions=unsure))
    for hedge in ("ظهر لي", "يظهر لي", "ظهرلي"):
        hedged = check(f"{hedge} سامي مكرز، يديه مكتفين.", langue="aeb", emotions=unsure)
        assert "emotion_incertaine" not in codes(hedged), hedge
    # « ظهر » alone is also the back: turning one's back is no nuance.
    back = check("سامي مكرز، يدير ظهرو ويديه مكتفين.", langue="aeb", emotions=unsure)
    assert "emotion_incertaine" in codes(back)
    angry = [{"emotion": "غضب", "certitude": 0.3}]
    assert "emotion_incertaine" not in codes(check("يظهر لي أنه غاضب، يقبض يديه.", langue="ar",
                                                   emotions=angry))


# The team's Derja notes: what is seen, a cautious reading, and an unfounded certainty.
def test_derja_notes_tell_seen_supposed_and_unfounded_apart():
    assert codes(check("عينيه يدمعوا، ويهبط راسو.", langue="aeb")) == {"ok"}       # seen
    assert codes(check("يبان عليه متقلق، خاطر قاعد يهبط في عينيه.", langue="aeb")) == {"ok"}
    assert "interpretation" in codes(check("يظهر عليه حزين.", langue="aeb"))       # no sign
    unfounded = check("هو أكيد مكتئب.", langue="aeb")
    assert "diagnostic" in codes(unfounded) and has_errors(unfounded)


def test_derja_notes_new_emotions_and_labels():
    for text in ("هي مبسوطة.", "سامي معصب.", "تبان متحشمة.", "قاعد مخنوق."):
        assert named_emotions(text, "aeb"), text
    for text in ("هي مجنونة.", "عندو ديبريسيون."):
        assert "diagnostic" in codes(check(text, langue="aeb")), text


def test_derja_notes_certainty_only_about_feelings():
    sure = check("مية بالمية متقلق، يهبط عينيه.", langue="aeb")
    assert "certitude" in codes(sure) and has_errors(sure)
    assert "certitude" in codes(check("بلا شك معصب، يقطب حواجبو.", langue="aeb"))
    # Certain about what is seen, not about a feeling: nothing to flag.
    assert codes(check("أكيد يحل الباب ويدخل.", langue="aeb")) == {"ok"}


def test_derja_notes_nuances_are_whole_phrases():
    unsure = [{"qui": "سامي", "emotion": "حزين", "certitude": 0.3}]
    for hedge in ("ينجم يكون", "يمكن", "على ما يظهر", "موش بالضرورة"):
        hedged = check(f"{hedge} حزين، يبكي.", langue="aeb", emotions=unsure)
        assert "emotion_incertaine" not in codes(hedged), hedge
    # « ما ينجمش يحكي » is « he can't speak », not a nuance.
    cannot = check("يبكي وما ينجمش يحكي، حزين.", langue="aeb", emotions=unsure)
    assert "emotion_incertaine" in codes(cannot)


def test_derja_notes_paraphrased_gestures_are_not_invented():
    # The model saw « يهبط عينيه »; the text says « ينكس راسو »: the same gesture, said otherwise.
    seen = ["سامي يهبط عينيه"]
    assert "signe_non_observe" not in codes(check_evidence(
        "سامي ينكس راسو ويقطب حواجبو.", langue="aeb", observations=seen))
    assert "signe_non_observe" in codes(check_evidence(
        "سامي يضحك ويهز كتافو.", langue="aeb", observations=seen))


def test_a_denied_certainty_is_a_nuance():
    sure = check("سامي sûr مكرز، يديه مكتفين.", langue="aeb")
    assert "certitude" in codes(sure) and has_errors(sure)
    assert "certitude" in codes(check("أكيد سامي مكرز، يديه مكتفين.", langue="aeb"))
    for denied in ("موش sûr", "موش أكيد", "مش واضح"):
        text = f"{denied} سامي مكرز، يديه مكتفين."
        assert "certitude" not in codes(check(text, langue="aeb")), denied
    assert "certitude" in codes(check("Karim est forcément furieux, il serre les poings."))
    assert "certitude" not in codes(check("Karim n'est pas forcément furieux, il serre les poings."))
    # A comma ends the negation: here « un pas » is a step.
    assert "certitude" in codes(check("Karim fait un pas, clairement furieux, les poings serrés."))


def test_review_flags_name_the_new_warnings():
    seg = Segment(id="p001", debut=0, fin=5, parole_debut=0.3, parole_fin=4.7, budget_mots=12,
                  brouillon_ia="Karim serre les poings, furieux.",
                  texte="Karim serre les poings, furieux.", confiance_ia=0.9)
    seg.verifications = check(seg.texte, emotions=[{"emotion": "colère", "certitude": 0.2}])
    assert review_flags(seg) == ["émotion incertaine"] and not validable_in_one_click(seg)


# --------------------------------------------------------------------------- reply and prompt
def test_the_reply_keeps_what_was_seen_apart_from_what_is_supposed():
    parsed = parse_reply(json.dumps({
        "observations": ["Karim serre les poings", "Leïla recule"],
        "emotions": [{"qui": "Karim", "emotion": "colère", "indices": ["poings serrés"],
                      "certitude": "70 %"}, "peur"],
        "description": "Karim serre les poings ; Leïla recule.", "confiance": 0.8},
        ensure_ascii=False))
    assert parsed["observations"] == ["Karim serre les poings", "Leïla recule"]
    assert parsed["emotions"][0] == {"qui": "Karim", "emotion": "colère",
                                     "indices": ["poings serrés"], "certitude": 0.7}
    assert parsed["emotions"][1] == {"qui": "", "emotion": "peur", "indices": [], "certitude": None}
    odd = parse_reply('{"description": "Il entre.", "observations": 3, "emotions": {"x": 1}}')
    assert odd["observations"] == [] and odd["emotions"] == []
    assert parse_reply("Il entre.")["emotions"] == []


def test_the_prompt_gives_each_image_its_time_and_the_emotion_rule():
    seg = Segment(id="p001", debut=10.0, fin=16.0, parole_debut=10.3, parole_fin=15.7,
                  budget_mots=12, images=["a", "b", "c", "d"], instants=[7.0, 8.5, 12.0, 14.0])
    common = {"film": "F", "intention_globale": "", "style": "", "personnages": [],
              "segment": seg, "langue": "fr"}
    prompt = build_draft_prompt(**common)
    assert "1 · 0:07,0 (juste avant la pause, pendant le dialogue)" in prompt
    assert "3 · 0:12,0 (pendant la pause)" in prompt
    assert "émotion probable" in prompt and '"observations"' in prompt
    assert "aucun mot d'émotion" in build_draft_prompt(**common, emotions_mode="signes")
    old = Segment(id="p002", debut=0, fin=4, parole_debut=0.3, parole_fin=3.7, budget_mots=8,
                  images=["a", "b"])
    assert "Les 2 images jointes" in build_draft_prompt(**{**common, "segment": old})
    assert "jamais un acteur" in SYSTEM_PROMPT and "diagnostic" in SYSTEM_PROMPT


def test_a_rewrite_uses_what_was_seen_without_the_images():
    model = Script(
        {"observations": ["Karim serre les poings", "Il fronce les sourcils"],
         "emotions": [{"qui": "Karim", "emotion": "colère",
                       "indices": ["poings serrés", "sourcils froncés"], "certitude": 0.8}],
         "description": "Karim est clairement furieux.", "confiance": 0.8},
        {"description": "Karim serre les poings et fronce les sourcils, l'air furieux.",
         "confiance": 0.8})
    seg = Segment(id="p003", debut=0, fin=6, parole_debut=0.3, parole_fin=5.7, budget_mots=12,
                  images=["a.jpg"])
    DescriberAgent(model, film="Test", langue="fr", personnages=[{"nom": "Karim"}],
                   log=quiet).describe(seg, [b"jpeg"], [])
    assert seg.texte == "Karim serre les poings et fronce les sourcils, l'air furieux."
    assert "1. Karim serre les poings ; 2. Il fronce les sourcils" in model.prompts[1]
    assert model.images[1] is None                      # the rewrite never resends the images
    assert seg.observations_ia == ["Karim serre les poings", "Il fronce les sourcils"]
    assert seg.emotions_ia[0]["emotion"] == "colère" and not has_errors(seg.verifications)
    assert validable_in_one_click(seg)


# --------------------------------------------------------------------------- frames, intent
def test_frames_from_just_before_the_pause(demo_files, tmp_path):
    path = prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], fournisseur="mock",
                   sortie=tmp_path / "avec", log=quiet)
    segments = load_project(path).segments
    for seg in segments:
        assert len(seg.images) == len(seg.instants) and seg.instants == sorted(seg.instants)
        before = [t for t in seg.instants if t < seg.debut]
        assert len(seg.instants) - len(before) == 2 and len(before) <= 2
        assert all(seg.debut - 3.0 - 1e-6 <= t for t in before) and min(seg.instants) >= 0
    with_context = [s for s in segments if any(t < s.debut for t in s.instants)]
    assert with_context
    first = next(rel for rel in with_context[0].images if "_avant" in rel)
    assert media.video_size(path.parent / first)[0] <= pipeline.CONTEXT_FRAME_WIDTH

    off = prepare(demo_files["video"], demo_files["intention"],
                  sous_titres=demo_files["sous_titres"], fournisseur="mock",
                  sortie=tmp_path / "sans", images_contexte=0, log=quiet)
    assert all(len(s.images) == 2 and min(s.instants) >= s.debut
               for s in load_project(off).segments)


def test_the_intent_file_sets_the_emotion_mode(tmp_path):
    def mode(line):
        intent = tmp_path / "intention.yaml"
        intent.write_text(f"film: Test\n{line}\n", encoding="utf-8")
        return load_intent(intent).emotions
    assert mode("") == "nuancees"
    assert mode("emotions: signes") == "signes"
    assert mode("emotions: Nuancées") == "nuancees"
    with pytest.raises(IntentError, match="signes"):
        mode("emotions: toutes")


# --------------------------------------------------------------------------- editor, report
def test_the_editor_shows_what_the_ai_saw_and_lets_a_person_decide(demo_files, tmp_path,
                                                                   monkeypatch):
    model = Script({"observations": ["Une main pose une tasse"], "emotions": [],
                    "description": "Une main pose une tasse sur la table.", "confiance": 0.9})
    monkeypatch.setattr(pipeline, "get_provider", lambda *args, **kwargs: model)
    path = prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], sortie=tmp_path / "projet", log=quiet)
    client = editor_client(path)
    client.post("/api/projet", json={"realisateur": "Nour"})
    seg = client.get("/api/projet").get_json()["segments"][-1]
    assert seg["observations_ia"] == ["Une main pose une tasse"]
    assert seg["images_info"][-1]["quand"] and seg["images_info"][-1]["avant"] is False
    # The director knows the character: their certainty is a warning, not a block.
    answer = client.post(f"/api/passage/{seg['id']}",
                         json={"action": "valider", "texte": "Clairement furieuse."})
    assert answer.status_code == 200
    assert "certitude" in codes(answer.get_json()["passage"]["verifications"])


def test_projects_made_before_the_upgrade_still_open(demo_files, tmp_path):
    path = prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], fournisseur="mock",
                   sortie=tmp_path / "ancien", log=quiet)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("emotions")
    for seg in data["segments"]:
        for key in ("instants", "observations_ia", "emotions_ia"):
            seg.pop(key)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    project = load_project(path)
    assert project.emotions == "nuancees" and project.segments[0].instants == []
    seg = editor_client(path).get("/api/projet").get_json()["segments"][0]
    assert all(image["quand"] == "" for image in seg["images_info"])


def test_the_report_counts_passages_that_name_an_emotion(tmp_path):
    def passage(seg_id, text):
        return Segment(id=seg_id, debut=0, fin=4, parole_debut=0.3, parole_fin=3.7,
                       budget_mots=12, brouillon_ia=text, texte=text, statut="valide")
    project = Project(film="F", video="f.mp4", duree=10, langue="fr", fournisseur="essai",
                      modele="m", personnages=[{"nom": "Joy"}],
                      segments=[passage("p001", "Joy ouvre la porte."),
                                passage("p002", "Elle serre les poings, l'air furieux.")])
    save_project(project, tmp_path / "projet.json")
    report = transparency_report(project, [], False)
    assert report["emotions"] == {"mode": "nuancees", "passages_nommant_une_emotion": 1}


def test_every_derja_word_is_in_the_review_file():
    # The native speaker reviews docs/DERJA_A_RELIRE.md: a word added to a list must be there.
    from pathlib import Path

    from wasf import emotions
    review = (Path(__file__).parent.parent / "docs" / "DERJA_A_RELIRE.md").read_text(encoding="utf-8")
    lists = (emotions.EMOTIONS, emotions.SIGNS, emotions.HEDGES, emotions.CERTAINTY,
             emotions.NEGATIONS, emotions.DIAGNOSES, emotions.JUDGEMENTS)
    missing = [w for words in lists for w in words["aeb"] if f"| {w} |" not in review]
    assert not missing, missing

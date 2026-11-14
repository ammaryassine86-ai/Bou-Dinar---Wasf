"""Change across frames, interactions, ambiguity, evidence checks and character continuity.

Model replies are scripted: these tests check what Wasf does with them, not what a model sees.
"""
import json

from wasf.agent import DescriberAgent, review_flags, run_checks
from wasf.continuity import character_memory
from wasf.emotions import check_evidence
from wasf.project import Segment
from wasf.prompts import build_draft_prompt, parse_reply
from wasf.providers import MockProvider, Provider

NAMES = ["Karim", "Leïla"]


def codes(checks):
    return {c["code"] for c in checks}


def evidence(text, observations=(), emotions=(), structured=True):
    return codes(check_evidence(text, langue="fr", observations=list(observations),
                                emotions=list(emotions), structured=structured, names=NAMES))


class Script(Provider):
    name, model = "essai", "script"

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate(self, system, user, images=None, meta=None):
        self.prompts.append(user)
        answer = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return json.dumps(answer, ensure_ascii=False)


def passage(seg_id="p002", debut=20.0, **fields):
    return Segment(id=seg_id, debut=debut, fin=debut + 5, parole_debut=debut + 0.3,
                   parole_fin=debut + 4.7, budget_mots=20, images=["a.jpg"], **fields)


# --------------------------------------------------------------------------- reply structure
def test_changes_and_interactions_are_kept_and_structure_problems_noted():
    parsed = parse_reply(json.dumps({
        "observations": ["Leïla rit"], "emotions": [],
        "changements": [{"qui": "Leïla", "avant": "rit", "apres": "baisse les yeux",
                         "images": [1, 3]}],
        "interactions": [{"qui": "Leïla", "envers": "Karim", "geste": "évite son regard"}],
        "description": "Leïla cesse de rire.", "confiance": 0.8}, ensure_ascii=False))
    assert parsed["changements"] == [{"qui": "Leïla", "avant": "rit", "apres": "baisse les yeux",
                                      "images": [1, 3]}]
    assert parsed["interactions"][0]["geste"] == "évite son regard"
    assert parsed["structure"] == []
    old_style = parse_reply('{"description": "Il entre.", "confiance": 0.9}')
    assert "« observations » absent" in old_style["structure"]


def test_structure_problems_go_to_the_journal():
    seg = passage()
    DescriberAgent(Script({"description": "Une porte s'ouvre.", "confiance": 0.9}),
                   film="F", langue="fr", log=lambda _m: None).describe(seg, [b"x"], [])
    assert any(step["etape"] == "structure" for step in seg.journal_agent)


# --------------------------------------------------------------------------- ambiguity
READINGS = [{"qui": "Leïla", "emotion": "malaise", "indices": ["regard fixe"], "certitude": 0.35},
            {"qui": "Leïla", "emotion": "colère", "indices": ["mâchoire serrée"],
             "certitude": 0.3}]


def test_competing_readings_are_allowed_but_not_settled_in_the_text():
    seen = ["Leïla a le regard fixe", "Sa mâchoire est serrée"]
    assert "emotion_ambigue" not in evidence("Leïla fixe Karim, la mâchoire serrée.", seen,
                                             READINGS)
    assert "emotion_ambigue" in evidence("Leïla fixe Karim, en colère.", seen, READINGS)
    sure = [dict(READINGS[0], certitude=0.8), READINGS[1]]
    assert "emotion_ambigue" not in evidence("Leïla fixe Karim, l'air mal à l'aise.", seen, sure)


# --------------------------------------------------------------------------- evidence
def test_an_emotion_named_without_its_signs():
    assert "sans_preuve" in evidence("Karim serre les poings, l'air en colère.",
                                     ["Karim serre les poings"],
                                     [{"qui": "Karim", "emotion": "colère", "indices": [],
                                       "certitude": 0.7}])


def test_evidence_the_model_did_not_observe():
    assert "indice_non_observe" in evidence(
        "Karim serre les poings, l'air furieux.", ["Karim serre les poings"],
        [{"qui": "Karim", "emotion": "colère", "indices": ["larmes aux yeux"], "certitude": 0.7}])


def test_gestures_that_share_nothing_with_the_observations():
    assert "signe_non_observe" in evidence("Leïla pleure et serre les poings.",
                                           ["Une voiture passe dans la rue"])
    # paraphrase is fine as long as something matches
    assert "signe_non_observe" not in evidence("Karim montre la porte du doigt et lève la main.",
                                               ["Karim tend la main vers la porte"])


def test_gestures_described_with_nothing_observed():
    assert "reponse_incomplete" in evidence("Leïla croise les bras.")
    assert "reponse_incomplete" not in evidence("Leïla croise les bras.", structured=False)
    assert "reponse_incomplete" not in evidence("Une voiture passe.")


def test_too_many_gestures_in_one_passage():
    text = ("Karim cligne des yeux, hoche la tête, se gratte la joue, lève la main, "
            "hausse les épaules et croise les bras.")
    assert "surcharge" in evidence(text, ["Karim bouge sans cesse"])


def test_evidence_checks_apply_to_the_ai_text_only():
    common = {"budget": 30, "avoid": [], "dialogue": "", "langue": "fr", "names": NAMES,
              "evidence": {"observations": [], "structured": True}}
    assert "reponse_incomplete" in codes(run_checks("Leïla croise les bras.", **common))
    assert "reponse_incomplete" not in codes(run_checks("Leïla croise les bras.", **common,
                                                        ai_text=False))


def test_a_simulation_is_not_flagged_for_missing_observations():
    seg = passage()
    DescriberAgent(MockProvider(), film="F", langue="fr",
                   log=lambda _m: None).describe(seg, [b"x"], [])
    assert "rien d'observé" not in review_flags(seg)


# --------------------------------------------------------------------------- continuity
def test_each_character_keeps_their_last_known_state():
    earlier = passage("p001", 5.0, texte="Leïla croise les bras.",
                      observations_ia=["Leïla croise les bras", "Karim parle fort"],
                      emotions_ia=[{"qui": "Leïla", "emotion": "agacement", "indices": [],
                                    "certitude": 0.4}],
                      interactions_ia=[{"qui": "Leïla", "envers": "Karim",
                                        "geste": "évite son regard"}])
    later = passage("p002", 12.0, texte="Karim s'assoit.", observations_ia=["Karim s'assoit"],
                    changements_ia=[{"qui": "Karim", "avant": "debout", "apres": "assis"}])
    lines = character_memory([earlier, later], NAMES)
    assert lines[0].startswith("Karim (0:12,0) : Karim s'assoit ; debout → assis")
    assert lines[1].startswith("Leïla (0:05,0) : Leïla croise les bras ; évite son regard envers Karim")
    assert "supposé : agacement (40 %)" in lines[1]
    assert character_memory([earlier], []) == []


def test_the_last_known_state_reaches_the_model():
    model = Script({"observations": ["Leïla décroise les bras"], "emotions": [],
                    "description": "Leïla décroise les bras.", "confiance": 0.9})
    seg = passage()
    DescriberAgent(model, film="F", langue="fr", personnages=[{"nom": "Leïla"}],
                   log=lambda _m: None).describe(
        seg, [b"x"], [], continuity=["Leïla (0:05,0) : Leïla croise les bras"])
    assert "Dernier état connu des personnages" in model.prompts[0]
    assert "- Leïla (0:05,0) : Leïla croise les bras" in model.prompts[0]


def test_the_prompt_asks_for_changes_interactions_and_every_reading():
    prompt = build_draft_prompt(film="F", intention_globale="", style="", personnages=[],
                                segment=passage(), langue="fr")
    assert '"changements"' in prompt and '"interactions"' in prompt
    from wasf.prompts import SYSTEM_PROMPT
    assert "toutes les lectures possibles" in SYSTEM_PROMPT
    assert "évite le regard" in SYSTEM_PROMPT and "sans importance" in SYSTEM_PROMPT

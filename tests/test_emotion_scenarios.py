"""The eight test scenes of the facial-expression upgrade, with SIMULATED model replies.

No image is analysed here. Each scene gives what a vision-language model could answer (a good
answer, and for some scenes a faulty one) and checks what Wasf does with it: the flags the
director sees, the blocks, the rewrite. Whether a real model reads these scenes correctly is
measured with real clips and a real model: see docs/TESTS_EMOTIONS.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from wasf.agent import DescriberAgent, has_errors, review_flags, validable_in_one_click
from wasf.project import Segment
from wasf.providers import Provider

PEOPLE = [{"nom": "Karim", "description": "homme d'une trentaine d'années, chemise bleue"},
          {"nom": "Leïla", "description": "femme d'une trentaine d'années, cheveux courts"}]


def reply(description, observations=(), emotions=(), confiance=0.85, changements=(),
          interactions=()):
    return {"observations": list(observations), "emotions": list(emotions),
            "changements": list(changements), "interactions": list(interactions),
            "description": description, "confiance": confiance}


@dataclass
class Scene:
    name: str
    replies: list[dict]                 # the draft, then the rewrites if the agent asks for one
    expected_flags: list[str]           # what the director sees on the passage
    dialogue_avant: str = ""
    dialogue_apres: str = ""
    previous: str = ""                  # the description of the passage before
    budget: int = 18
    instants: list[float] = field(default_factory=lambda: [8.0, 9.5, 11.5, 13.5])


class Script(Provider):
    name, model = "essai", "script"

    def __init__(self, replies):
        self.replies, self.prompts, self.images = list(replies), [], []

    def generate(self, system, user, images=None, meta=None):
        self.prompts.append(user)
        self.images.append(images)
        answer = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return json.dumps(answer, ensure_ascii=False)


SCENES = [
    Scene("1. Conversation, deux expressions",
          [reply("Karim sourit en parlant ; face à lui, Leïla fronce les sourcils.",
                 ["Karim parle en souriant", "Leïla l'écoute, les sourcils froncés"])],
          [], dialogue_avant="Tu as eu le poste ?", dialogue_apres="Oui… enfin, je crois."),
    Scene("2a. Un personnage pleure",
          [reply("Des larmes coulent sur les joues de Leïla ; elle s'essuie les yeux.",
                 ["Des larmes sur les joues de Leïla", "Elle s'essuie les yeux"],
                 [{"qui": "Leïla", "emotion": "tristesse", "indices": ["larmes"],
                   "certitude": 0.7}])],
          []),
    Scene("2b. Pleurs, réponse fautive : émotion sans signe",
          [reply("Leïla est dévastée.", ["Des larmes sur les joues de Leïla"])],
          ["interprétation possible"]),
    Scene("3. Colère : visage et gestes (brouillon trop sûr, puis réécrit)",
          [reply("Karim est clairement furieux.",
                 ["Karim serre les poings", "Il fronce les sourcils"],
                 [{"qui": "Karim", "emotion": "colère",
                   "indices": ["poings serrés", "sourcils froncés"], "certitude": 0.8}]),
           reply("Karim serre les poings et fronce les sourcils, l'air furieux.")],
          []),
    Scene("4a. Un sourire qui cache peut-être un malaise",
          [reply("Leïla sourit, mais ses mains tremblent autour de sa tasse.",
                 ["Leïla sourit", "Ses mains tremblent autour de la tasse"],
                 [{"qui": "Leïla", "emotion": "malaise", "indices": ["mains qui tremblent"],
                   "certitude": 0.4}])],
          []),
    Scene("4b. Même scène, réponse fautive : intention devinée",
          [reply("Leïla fait semblant d'être heureuse et dissimule sa tristesse.",
                 ["Leïla sourit"],
                 [{"qui": "Leïla", "emotion": "tristesse", "indices": [], "certitude": 0.3}])],
          ["interprétation possible", "émotion incertaine", "émotion sans signe donné"]),
    Scene("5. Montrer du doigt, saluer de la main",
          [reply("Karim montre la porte du doigt. Sur le trottoir, Leïla lui fait signe de la main.",
                 ["Karim tend le bras vers la porte", "Leïla agite la main sur le trottoir"])],
          [], budget=20),
    Scene("6a. Dispute par le langage du corps",
          [reply("Karim se penche vers Leïla en agitant les mains ; elle recule et croise les bras.",
                 ["Karim se penche vers Leïla", "Il agite les mains", "Leïla recule",
                  "Elle croise les bras"])],
          [], budget=20),
    Scene("6b. Passage suivant de la dispute : mêmes gestes redécrits",
          [reply("Les bras toujours croisés, Leïla recule encore ; Karim agite les mains.",
                 ["Leïla garde les bras croisés", "Karim agite les mains"])],
          ["geste déjà décrit"],
          previous="Karim se penche vers Leïla en agitant les mains ; elle recule et croise les bras."),
    Scene("6c. Passage suivant, ce qui a changé",
          [reply("Karim s'arrête net et baisse la voix ; Leïla décroise les bras.",
                 ["Karim s'arrête et baisse la voix", "Leïla décroise les bras"])],
          [],
          previous="Karim se penche vers Leïla en agitant les mains ; elle recule et croise les bras."),
    Scene("7. De la joie à la tristesse (images avant et pendant la pause)",
          [reply("Le rire de Leïla s'arrête ; son sourire s'efface et elle baisse les yeux.",
                 ["0:08 Leïla rit", "0:13 son sourire s'efface, elle baisse les yeux"],
                 [{"qui": "Leïla", "emotion": "tristesse",
                   "indices": ["sourire qui s'efface", "yeux baissés"], "certitude": 0.6}],
                 changements=[{"qui": "Leïla", "avant": "rit", "apres": "baisse les yeux",
                               "images": [2, 4]}])],
          []),
    Scene("7b. Interaction : un regard évité",
          [reply("Karim tend la main ; Leïla détourne le regard et recule d'un pas.",
                 ["Karim tend la main vers Leïla", "Leïla détourne le regard",
                  "Elle recule d'un pas"],
                 interactions=[{"qui": "Leïla", "envers": "Karim",
                                "geste": "détourne le regard, recule"}])],
          []),
    Scene("8a. Émotion ambiguë : l'IA décrit et se dit peu sûre",
          [reply("Leïla fixe la fenêtre, immobile.", ["Leïla fixe la fenêtre sans bouger"],
                 [{"qui": "Leïla", "emotion": "inquiétude", "indices": [], "certitude": 0.3}],
                 confiance=0.4)],
          ["IA peu sûre (elle se note 0,4 sur 1)"]),
    Scene("8c. Scène ambiguë, deux lectures : le texte ne tranche pas",
          [reply("Leïla fixe Karim, la mâchoire serrée.",
                 ["Leïla fixe Karim", "Sa mâchoire est serrée"],
                 [{"qui": "Leïla", "emotion": "colère", "indices": ["mâchoire serrée"],
                   "certitude": 0.35},
                  {"qui": "Leïla", "emotion": "peur", "indices": ["regard fixe"],
                   "certitude": 0.3}])],
          []),
    Scene("8d. Deux lectures, réponse fautive : elle en choisit une",
          [reply("Leïla fixe Karim, en colère.",
                 ["Leïla fixe Karim", "Sa mâchoire est serrée"],
                 [{"qui": "Leïla", "emotion": "colère", "indices": ["mâchoire serrée"],
                   "certitude": 0.35},
                  {"qui": "Leïla", "emotion": "peur", "indices": ["regard fixe"],
                   "certitude": 0.3}])],
          ["plusieurs lectures possibles", "émotion incertaine"]),
    Scene("8b. Même scène, réponse fautive : elle tranche",
          [reply("Leïla est inquiète.", ["Leïla fixe la fenêtre sans bouger"],
                 [{"qui": "Leïla", "emotion": "inquiétude", "indices": [], "certitude": 0.3}],
                 confiance=0.7)],
          ["interprétation possible", "émotion incertaine"]),
]


def run(scene: Scene):
    """Describe the scene's passage with the scripted model; return the passage and the model."""
    seg = Segment(id="p010", debut=11.0, fin=15.0, parole_debut=11.3, parole_fin=14.7,
                  budget_mots=scene.budget, images=[f"i{k}.jpg" for k in range(4)],
                  instants=list(scene.instants), dialogue_avant=scene.dialogue_avant,
                  dialogue_apres=scene.dialogue_apres)
    model = Script(scene.replies)
    DescriberAgent(model, film="Essai", langue="fr", personnages=PEOPLE,
                   log=lambda _m: None).describe(seg, [b"jpeg"] * 4, [], previous=scene.previous)
    return seg, model


@pytest.mark.parametrize("scene", SCENES, ids=[s.name for s in SCENES])
def test_scene(scene):
    seg, _model = run(scene)
    assert sorted(review_flags(seg)) == sorted(scene.expected_flags)
    assert not has_errors(seg.verifications)
    assert validable_in_one_click(seg) == (not scene.expected_flags)
    assert seg.observations_ia == scene.replies[0]["observations"]


def test_the_model_is_told_which_images_come_before_the_pause():
    _seg, model = run(next(s for s in SCENES if s.name.startswith("7.")))
    assert "1 · 0:08,0 (juste avant la pause, pendant le dialogue)" in model.prompts[0]
    assert "3 · 0:11,5 (pendant la pause)" in model.prompts[0]


def test_an_overconfident_draft_is_rewritten_from_what_was_seen():
    seg, model = run(next(s for s in SCENES if s.name.startswith("3.")))
    assert len(model.prompts) == 2 and model.images[1] is None
    assert "1. Karim serre les poings ; 2. Il fronce les sourcils" in model.prompts[1]
    assert seg.texte == "Karim serre les poings et fronce les sourcils, l'air furieux."
    assert seg.journal_agent[0]["texte"] == "Karim est clairement furieux."


def test_changes_and_interactions_are_kept_on_the_passage():
    seg, _model = run(next(s for s in SCENES if s.name.startswith("7.")))
    assert seg.changements_ia[0]["apres"] == "baisse les yeux"
    seg, _model = run(next(s for s in SCENES if s.name.startswith("7b.")))
    assert seg.interactions_ia[0]["envers"] == "Karim"

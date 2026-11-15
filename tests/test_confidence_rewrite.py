"""Confidence after a text-only rewrite (audit of 15/11/2026, finding 2). The rewrite does not
see the images: its mark may lower the one the draft was given, never raise it. A passage the
model doubted used to lose its alert, and become validable in one click, after a blind rewrite."""
import json

import pytest

from wasf.agent import (
    DescriberAgent,
    confidence_after_rewrite,
    review_flags,
    validable_in_one_click,
)
from wasf.project import Segment
from wasf.providers import Provider

TOO_LONG = "Un homme ouvre lentement une lourde porte en bois sombre et entre dans la pièce."


class Scripted(Provider):
    """Returns the replies in order: the draft, then each rewrite."""

    name, model = "essai", "script"

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def generate(self, system, user, images=None, meta=None):
        self.calls.append((meta or {}).get("mode"))
        return self.replies.pop(0)


def draft(confidence, text=TOO_LONG):
    reply = {"observations": ["un homme ouvre une porte"], "changements": [], "interactions": [],
             "emotions": [], "description": text, "appuis": [[1]], "remarque": ""}
    if confidence is not None:
        reply["confiance"] = confidence
    return json.dumps(reply, ensure_ascii=False)


def rewrite(confidence, text="Un homme ouvre la porte et entre."):
    reply = {"description": text, "appuis": [[1]], "remarque": ""}
    if confidence is not None:
        reply["confiance"] = confidence
    return json.dumps(reply, ensure_ascii=False)


def described(*replies):
    seg = Segment(id="p001", debut=10.0, fin=14.0, parole_debut=10.3, parole_fin=13.7,
                  budget_mots=8, images=["a.jpg"], instants=[11.0])
    model = Scripted(*replies)
    DescriberAgent(model, film="Test", langue="fr", log=lambda _m: None).describe(seg, [b"jpeg"])
    return seg, model.calls


@pytest.mark.parametrize("seen, rewritten, kept", [(0.3, 0.95, 0.3), (0.8, 0.4, 0.4),
                                                   (0.7, None, 0.7), (None, 0.9, None),
                                                   (None, None, None), (0.6, 0.6, 0.6)])
def test_the_rule(seen, rewritten, kept):
    assert confidence_after_rewrite(seen, rewritten) == kept


def test_a_blind_rewrite_cannot_lift_a_doubt():
    seg, calls = described(draft(0.3), rewrite(0.95))
    assert calls == ["brouillon", "revision"]
    assert seg.confiance_ia == 0.3
    assert "IA peu sûre (elle se note 0,3 sur 1)" in review_flags(seg)
    assert not validable_in_one_click(seg)
    # The journal still says what the rewrite claimed.
    assert [step.get("confiance") for step in seg.journal_agent
            if step["etape"] == "revision 1"] == [0.95]


def test_a_rewrite_that_cuts_can_lower_it():
    seg, _ = described(draft(0.8), rewrite(0.4))
    assert seg.confiance_ia == 0.4 and any("peu sûre" in f for f in review_flags(seg))


def test_an_unknown_draft_mark_stays_unknown():
    seg, _ = described(draft(None), rewrite(0.9))
    assert seg.confiance_ia is None and "confiance de l'IA inconnue" in review_flags(seg)


def test_a_rewrite_without_a_mark_keeps_the_draft_one():
    seg, _ = described(draft(0.7), rewrite(None))
    assert seg.confiance_ia == 0.7


def test_the_lowest_mark_of_several_rewrites_is_kept():
    still_long = "Un homme ouvre lentement la lourde porte en bois et il entre dans la pièce."
    seg, calls = described(draft(0.8), rewrite(0.9, still_long), rewrite(0.6))
    assert calls == ["brouillon", "revision", "revision"] and seg.confiance_ia == 0.6


def test_without_a_rewrite_nothing_changes():
    seg, calls = described(draft(0.9, "Un homme ouvre la porte."))
    assert calls == ["brouillon"] and seg.confiance_ia == 0.9

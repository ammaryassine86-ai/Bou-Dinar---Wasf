"""What the exports say (audit of 15/11/2026). The AI notice now opens the SRT, which had none
(finding 7), and the credits promise only what Wasf can keep (finding 8): Wasf trains no model,
but an online provider's terms are its own; the emotion rules flag, they do not guarantee."""
from editeur_client import editor_client

from wasf.export import (
    NOTICE_MIN_SECONDS,
    _emotions_line,
    _training_lines,
    label_text,
    notice_seconds,
    write_srt,
)
from wasf.pipeline import RenderOptions, render
from wasf.project import Segment, load_project

NOTICE = "Audiodescription écrite par intelligence artificielle, validée par Réalisatrice A."


def _segments():
    return [Segment(id="p001", debut=0.0, fin=3.0, parole_debut=0.3, parole_fin=2.7,
                    budget_mots=6, texte="Amel ouvre la porte."),
            Segment(id="p002", debut=9.0, fin=13.0, parole_debut=9.3, parole_fin=12.7,
                    budget_mots=8, texte="Slah range les chaises.")]


def _cues(path):
    return [block.splitlines()
            for block in path.read_text(encoding="utf-8").strip().split("\n\n")]


def test_the_srt_opens_with_the_ai_notice(tmp_path):
    cues = _cues(write_srt(_segments(), tmp_path / "a.srt", NOTICE, 4.4))
    assert cues[0] == ["1", "00:00:00,000 --> 00:00:04,400", NOTICE]
    # A description that starts within those seconds is shown with it, numbered after it.
    assert cues[1] == ["2", "00:00:00,300 --> 00:00:02,700", "Amel ouvre la porte."]
    assert [cue[0] for cue in cues] == ["1", "2", "3"]


def test_without_a_notice_the_srt_is_as_before(tmp_path):
    cues = _cues(write_srt(_segments(), tmp_path / "a.srt"))
    assert cues[0] == ["1", "00:00:00,300 --> 00:00:02,700", "Amel ouvre la porte."]
    assert len(cues) == 2


def test_the_notice_stays_on_screen_as_long_as_it_takes_to_say_it():
    assert notice_seconds("Version de travail.", "fr") == NOTICE_MIN_SECONDS
    twenty_words = " ".join(["mot"] * 20)
    assert notice_seconds(twenty_words, "fr") == 8.0             # 2.5 words a second
    assert notice_seconds(twenty_words, "aeb") == round(20 / 2.2, 1)
    assert notice_seconds(twenty_words, "fr", rate=4.0) == 5.0   # the director's own rate


def test_the_credits_promise_only_what_wasf_keeps():
    promise = "Wasf n'entraîne aucun modèle d'IA sur ce film."
    assert _training_lines("essai") == [promise] and _training_lines("ollama") == [promise]
    for provider in ("gemini", "anthropic", "openai"):
        lines = _training_lines(provider)
        assert lines[0] == promise and f"« {provider} »" in lines[1]
        assert "ne peut pas vérifier" in lines[1]

    nuanced = _emotions_line({"mode": "nuancees", "passages_nommant_une_emotion": 3})
    assert "avait pour consigne" in nuanced and "jamais" not in nuanced
    assert "(3 passage(s) nomment une émotion)" in nuanced
    signs = _emotions_line({"mode": "signes", "passages_nommant_une_emotion": 0})
    assert "avait pour consigne" in signs and "quand même" not in signs
    assert "(1 passage(s) en nomment une quand même)" in _emotions_line(
        {"mode": "signes", "passages_nommant_une_emotion": 1})


def test_an_export_carries_the_notice_and_the_new_credits(real_path):
    client = editor_client(real_path)
    client.post("/api/projet", json={"realisateur": "Réalisatrice A"})
    for seg in load_project(real_path).segments:
        response = client.post(f"/api/passage/{seg.id}", json={"action": "valider"})
        assert response.status_code == 200, response.get_json()
    assert client.post("/api/projet", json={"validation_realisateur": True}).status_code == 200
    out = render(real_path, RenderOptions(moteur="bip", annonce=False), log=lambda _m: None)

    first = _cues(out["sous_titres_srt"])[0]
    assert first[0] == "1" and first[1].startswith("00:00:00,000 --> ")
    assert first[2] == label_text(load_project(real_path)) == NOTICE + " Approuvée par la réalisation."
    assert "NOTE" in out["sous_titres_vtt"].read_text(encoding="utf-8")   # unchanged

    credits = out["credits"].read_text(encoding="utf-8")
    assert "Wasf n'entraîne aucun modèle d'IA sur ce film." in credits
    assert "jamais utilisé pour entraîner" not in credits
    assert "jamais avec certitude" not in credits and "avait pour consigne" in credits

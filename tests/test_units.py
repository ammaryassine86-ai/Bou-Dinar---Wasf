import shutil

import numpy as np
import pytest
import yaml

from wasf.agent import count_words, has_errors, review_flags, run_checks, validable_in_one_click
from wasf.demo import make_demo
from wasf.gaps import Cue, gaps_from_cues, parse_subtitles, split_long, Window
from wasf.intent import IntentError, RightsError, load_intent
from wasf.mix import duck
from wasf.project import Segment
from wasf.prompts import build_draft_prompt, build_revision_prompt, parse_reply
from wasf.providers import MockProvider, _shorten
from wasf.story import story_so_far
from wasf.textnorm import dialogue_language
from wasf.timecode import fmt_tc, parse_tc


def test_timecodes():
    assert parse_tc("00:01:02,500") == pytest.approx(62.5)
    assert parse_tc("01:02.25") == pytest.approx(62.25)
    assert parse_tc(90) == 90.0
    assert parse_tc("12.5") == 12.5
    assert fmt_tc(62.5) == "00:01:02.500"
    assert fmt_tc(3725.042, ",") == "01:02:05,042"
    with pytest.raises(ValueError):
        parse_tc("bientôt")


def test_parse_srt_and_vtt(tmp_path):
    srt = tmp_path / "a.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,500\n<i>Bonjour</i>\n\n"
                   "2\n00:00:05,000 --> 00:00:06,000 position:50%\nسلام\n", encoding="utf-8")
    cues = parse_subtitles(srt)
    assert [(c.start, c.end, c.text) for c in cues] == [(1.0, 2.5, "Bonjour"), (5.0, 6.0, "سلام")]
    vtt = tmp_path / "a.vtt"
    vtt.write_text("WEBVTT\n\nNOTE test\n\n00:01.000 --> 00:02.000\nSalut\n", encoding="utf-8")
    assert parse_subtitles(vtt)[0].text == "Salut"


def test_gaps_and_split():
    cues = [Cue(2.0, 5.0, "a"), Cue(5.5, 6.0, "b"), Cue(15.0, 16.0, "c")]
    gaps = gaps_from_cues(cues, 20.0, min_gap=1.6)
    assert [(g.start, g.end) for g in gaps] == [(0.0, 2.0), (6.0, 15.0), (16.0, 20.0)]
    parts = split_long([Window(0.0, 20.0, "silence")], max_len=8.0)
    assert len(parts) == 3 and parts[-1].end == pytest.approx(20.0)


def test_checks_budget_avoid_echo_and_arabic():
    ok = run_checks("Amel pose la tasse.", budget=6, avoid=[], dialogue="", langue="fr")
    assert ok[0]["code"] == "ok" and not has_errors(ok)
    long = run_checks("un deux trois quatre cinq six sept", budget=5, avoid=[], dialogue="", langue="fr")
    assert any(c["code"] == "trop_long" for c in long)
    avoid = run_checks("Le visiteur entre.", budget=10, avoid=["visiteur"], dialogue="", langue="fr")
    assert any(c["code"] == "a_eviter" for c in avoid)
    echo = run_checks("Regarde bien l'écran tout de suite", budget=10, avoid=[],
                      dialogue="Regarde bien l'écran tout de suite !", langue="fr")
    assert any(c["code"] == "repetition_dialogue" for c in echo)
    warn = run_checks("Elle semble inquiète.", budget=10, avoid=[], dialogue="", langue="fr")
    assert any(c["code"] == "interpretation" for c in warn) and not has_errors(warn)
    assert count_words("أمل تضع الفنجان على الطاولة") == 5
    arabic = run_checks("أمل تبدو حزينة", budget=5, avoid=[], dialogue="", langue="ar")
    assert any(c["code"] == "interpretation" for c in arabic)
    assert run_checks("", budget=5, avoid=[], dialogue="", langue="fr")[0]["code"] == "vide"


def test_parse_reply_variants():
    assert parse_reply('{"description": "Amel sort.", "confiance": 0.8}')["description"] == "Amel sort."
    fenced = parse_reply('```json\n{"description": "Slah sourit.", "confiance": "2"}\n```')
    # Above 1 reads as a percentage (2 %), never as full confidence.
    assert fenced["description"] == "Slah sourit." and fenced["confiance"] == pytest.approx(0.02)
    plain = parse_reply("Une porte s'ouvre.")
    assert plain["description"] == "Une porte s'ouvre." and plain["confiance"] is None


def test_mock_shortens_cleanly():
    assert _shorten("Un carré glisse vers la droite sur un fond bleu. Rien ne bouge.", 7) \
        == "Un carré glisse vers la droite."
    reply = MockProvider().generate("", "", None, {"mode": "revision", "budget": 4, "langue": "fr",
                                                   "brouillon": "Le visiteur ouvre la porte du café.",
                                                   "a_eviter": ["visiteur"]})
    assert "visiteur" not in parse_reply(reply)["description"].lower()


def test_intent_rights_and_errors(tmp_path):
    path = tmp_path / "i.yaml"
    path.write_text("film: Test\nlangue: aeb\nscenes:\n  - {debut: '00:00:05', fin: '00:00:10', "
                    "a_remarquer: Amel, a_eviter: visiteur}\n", encoding="utf-8")
    intent = load_intent(path)
    assert intent.langue == "aeb" and intent.scenes[0].a_eviter == ["visiteur"]
    assert intent.notes_for(8, 12)["a_remarquer"] == "Amel"
    assert intent.notes_for(11, 12)["a_remarquer"] == ""
    with pytest.raises(RightsError):
        intent.check_rights()
    path.write_text("langue: fr\n", encoding="utf-8")
    with pytest.raises(IntentError):
        load_intent(path)


def test_story_so_far_is_past_only_and_bounded():
    cues = [Cue(1.0, 2.0, "Bonjour Amel."), Cue(9.0, 10.0, "Il arrive."),
            Cue(20.0, 21.0, "C'est lui !")]
    described = [(2.5, "Amel pose la tasse."), (12.0, "Slah entre.")]
    story = story_so_far(cues, described, before=12.0)
    text = " ".join(story)
    assert "Bonjour Amel." in text and "Amel pose la tasse." in text and "Il arrive." in text
    assert "C'est lui" not in text and "Slah entre." not in text  # later in the film
    assert story[0].startswith("0:01,0")  # oldest first
    short = story_so_far(cues, described, before=12.0, max_chars=60)
    assert len(short) == 1 and "Il arrive." in short[0]  # the most recent line is kept


def test_lexicon_examples_and_avoid_in_the_film_words(tmp_path):
    path = tmp_path / "i.yaml"
    path.write_text("film: Test\nlangue: aeb\n"
                    "lexique:\n  téléphone portable: البورتابل\n  lettre: رسالة\n"
                    "exemples:\n  - أمل تحط البورتابل على الطاولة وتخزر للباب.\n"
                    "scenes:\n  - {debut: '00:00:00', fin: '00:00:10', a_eviter: [Lettre]}\n",
                    encoding="utf-8")
    intent = load_intent(path)
    assert intent.lexique["téléphone portable"] == "البورتابل" and len(intent.exemples) == 1
    assert intent.notes_for(0, 5)["a_eviter"] == sorted({"Lettre", "رسالة"})
    seg = Segment(id="p001", debut=0.0, fin=5.0, parole_debut=0.3, parole_fin=4.7, budget_mots=9)
    prompt = build_draft_prompt(film="Test", intention_globale="", style="", personnages=[],
                                segment=seg, langue="aeb", story=["0:01,0 · dialogue : « Ahla »"],
                                lexique=intent.lexique, exemples=intent.exemples)
    assert "téléphone portable → البورتابل" in prompt and intent.exemples[0] in prompt
    assert "Ahla" in prompt and "Jamais d'arabe standard" in prompt
    path.write_text("film: Test\nlexique: [chéchia]\n", encoding="utf-8")
    with pytest.raises(IntentError):
        load_intent(path)


def test_a_derja_track_is_told_how_derja_sounds():
    # A real Gemini run wrote « تظلم الصورة تدريجيا », copying a note in Standard Arabic.
    seg = Segment(id="p001", debut=0.0, fin=5.0, parole_debut=0.3, parole_fin=4.7, budget_mots=9)
    draft = build_draft_prompt(film="Test", intention_globale="", style="", personnages=[],
                               segment=seg, langue="aeb", story=[])
    revision = build_revision_prompt(draft="مستطيل أصفر يتحرك ببطء.", problems=["Trop long."],
                                     budget=4, langue="aeb")
    for prompt in (draft, revision):
        assert "reprends leur sens, jamais leurs mots" in prompt
        assert "بالشوية (pas ببطء)" in prompt and "بشوية بشوية (pas تدريجيا)" in prompt
        assert "تقعد حذا الشباك وتغزر للبحر" in prompt
    french = build_draft_prompt(film="Test", intention_globale="", style="", personnages=[],
                                segment=seg, langue="fr", story=[])
    assert "بالشوية" not in french


def test_the_track_language_follows_the_dialogue():
    assert dialogue_language("— Tu as vu ? Il recommence. — Regarde l'écran, vite !") == "fr"
    assert dialogue_language("— شفت؟ عاود من جديد. — هاذي الإشارة اللي نستناو فيها.") == "aeb"
    assert dialogue_language("سوف أذهب إلى البيت الذي تعرفه، لكن ليس الآن.") == "ar"
    assert dialogue_language("") is None and dialogue_language("OK.") is None


def test_the_derja_demo_gives_derja_notes_and_examples(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg n'est pas installé")
    files = make_demo(tmp_path, "aeb")
    data = yaml.safe_load(files["intention"].read_text(encoding="utf-8"))
    notes = " ".join(scene["a_remarquer"] for scene in data["scenes"]) + data["intention_globale"]
    assert data["langue"] == "aeb" and "بالشوية" in notes
    assert not any(word in notes for word in ("ببطء", "تدريجيا", "ينزلق", "نحو"))
    assert len(load_intent(files["intention"]).exemples) == 2


def test_review_flags_decide_what_the_director_checks():
    seg = Segment(id="p001", debut=0.0, fin=5.0, parole_debut=0.3, parole_fin=4.7, budget_mots=9,
                  brouillon_ia="Amel pose la tasse.", texte="Amel pose la tasse.", confiance_ia=0.8)
    seg.verifications = run_checks(seg.texte, budget=9, avoid=[], dialogue="", langue="fr")
    assert review_flags(seg) == [] and validable_in_one_click(seg)
    seg.confiance_ia = 0.3  # the model says it is unsure
    # Lot 3, point G: the model's own mark, never shown like a probability of being right.
    assert review_flags(seg) == ["IA peu sûre (elle se note 0,3 sur 1)"]
    assert not validable_in_one_click(seg)
    seg.confiance_ia = 0.9
    seg.texte = seg.brouillon_ia = "Elle semble inquiète."
    seg.verifications = run_checks(seg.texte, budget=9, avoid=[], dialogue="", langue="fr")
    assert review_flags(seg) == ["interprétation possible"]
    seg.texte, seg.verifications = "", run_checks("", budget=9, avoid=[], dialogue="", langue="fr")
    assert "rien de décrit" in review_flags(seg)


def test_duck_envelope():
    gain = np.ones(1000, dtype=np.float32)
    duck(gain, 400, 600, 0.25, 50)
    assert gain[0] == 1.0 and gain[500] == pytest.approx(0.25) and gain[-1] == 1.0
    assert 0.25 < gain[370] < 1.0

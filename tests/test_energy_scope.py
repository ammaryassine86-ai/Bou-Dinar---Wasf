"""Lot 3, points I and G.

I: the transparency report says what its energy figures cover (this computer) and what they
leave out (an online provider's servers), and counts the calls to the model behind the texts,
with images or text only. Nothing is estimated for the servers: Wasf has no access to them.

G: the model's confidence is its own mark, not a probability of being right. The review flag
said « IA peu sûre (30 %) », which reads like a measured probability; it now says the mark the
model gives itself."""
import json

from wasf.agent import review_flags
from wasf.export import energy_scope, model_calls
from wasf.pipeline import RenderOptions, render
from wasf.project import Project, Segment, load_project, now_iso, save_project

DIRECTOR = "Réalisatrice A"


def _project(fournisseur: str, seconde_lecture: str = "") -> Project:
    return Project(film="Essai", video="film.mp4", duree=10.0, langue="fr",
                   fournisseur=fournisseur, modele="m", seconde_lecture=seconde_lecture)


def _segment(seg_id: str, steps: list[dict]) -> Segment:
    seg = Segment(id=seg_id, debut=0.0, fin=5.0, parole_debut=0.3, parole_fin=4.7, budget_mots=9)
    seg.journal_agent = steps
    return seg


def test_calls_are_counted_from_the_traces():
    project = _project("gemini")
    project.segments = [
        _segment("p001", [{"etape": "brouillon"}, {"etape": "verification 1"},
                          {"etape": "revision 1"}, {"etape": "verification 2"},
                          {"etape": "seconde lecture", "resultats": []}]),
        _segment("p002", [{"etape": "erreur", "message": "429"}]),
        _segment("p003", [{"etape": "brouillon"}, {"etape": "structure"}, {"etape": "refus"}]),
    ]
    calls = model_calls(project)
    assert (calls["avec_images"], calls["texte_seul"], calls["en_echec"]) == (3, 1, 1)
    assert calls["reels"] is True


def test_a_simulation_makes_no_real_call_and_uses_no_server():
    project = _project("mock")
    assert model_calls(project)["reels"] is False
    assert energy_scope(project)["hors_mesure"].startswith("rien : simulation")


def test_what_the_energy_figures_leave_out_is_said():
    online = energy_scope(_project("gemini"))
    assert "cet ordinateur" in online["mesure"]
    assert "serveurs du fournisseur (gemini)" in online["hors_mesure"]
    assert "n'est pas mesurée" in online["hors_mesure"]
    local = energy_scope(_project("ollama"))["hors_mesure"]
    assert "cet ordinateur" in local and "autre machine" in local
    mixed = energy_scope(_project("ollama", seconde_lecture="gemini:gemini-3.6-flash"))
    assert "seconde lecture (gemini:gemini-3.6-flash)" in mixed["hors_mesure"]
    assert "seconde lecture" not in energy_scope(_project("ollama", "même modèle"))["hors_mesure"]


def test_the_report_carries_both(real_path):
    project = load_project(real_path)
    project.realisateur = DIRECTOR
    for seg in project.segments:
        seg.statut, seg.valide_par, seg.valide_le = "valide", DIRECTOR, now_iso()
    project.validation_realisateur, project.approuve_par = True, DIRECTOR
    save_project(project, real_path)
    outputs = render(real_path, RenderOptions(moteur="bip", annonce=False), log=lambda _m: None)
    report = json.loads(outputs["rapport"].read_text(encoding="utf-8"))
    assert report["appels_au_modele"]["avec_images"] == len(project.segments)   # one draft each
    assert report["appels_au_modele"]["reels"] is True
    assert "n'est pas mesurée" in report["energie_portee"]["hors_mesure"]


def test_confidence_is_shown_as_the_models_own_mark():
    seg = _segment("p001", [])
    seg.brouillon_ia = seg.texte = "Amel pose la tasse."
    seg.confiance_ia = 0.35
    assert "IA peu sûre (elle se note 0,35 sur 1)" in review_flags(seg)
    assert not any("%" in flag for flag in review_flags(seg))

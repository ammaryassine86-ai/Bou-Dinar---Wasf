"""Lot 3, point J: an error that would come back for every passage (refused key, unknown model,
the day's quota or credit used up, Ollama not running) stops the preparation at once. Every
finished passage is kept, the history says why the run stopped, and --reprendre
--refaire-echecs goes on without asking the AI again for what is done.

Before: such an error failed the remaining passages one after the other, each one a call that
could only fail, and the run ended with a track full of empty passages."""
import pytest
import requests

from wasf import pipeline
from wasf.agent import DescriberAgent
from wasf.cli import main
from wasf.pipeline import prepare
from wasf.project import load_project
from wasf.providers import MockProvider, OllamaProvider, ProviderError, is_fatal


class _Status(Exception):
    """An SDK error that carries its HTTP status, like Claude's or OpenAI's."""

    def __init__(self, status: int, text: str = ""):
        super().__init__(text or f"Error code: {status}")
        self.status_code = status


class _GoogleError(Exception):
    """Gemini's errors carry the status in .code."""

    def __init__(self, code: int, text: str):
        super().__init__(f"{code} {text}")
        self.code = code


@pytest.mark.parametrize("exc", [
    _Status(401, "invalid x-api-key"),
    _Status(403, "PERMISSION_DENIED"),
    _Status(404, "model: claude-x not found"),
    _GoogleError(429, "RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
    _GoogleError(400, "INVALID_ARGUMENT API key not valid. Please pass a valid API key."),
    _Status(429, "You exceeded your current quota. 'code': 'insufficient_quota'"),
    _Status(400, "Your credit balance is too low to access the Anthropic API."),
    requests.ConnectionError("[Errno 111] Connection refused"),
])
def test_errors_every_passage_would_meet_are_fatal(exc):
    assert is_fatal(exc)


@pytest.mark.parametrize("exc", [
    _GoogleError(429, "RESOURCE_EXHAUSTED GenerateRequestsPerMinutePerProjectPerModel"),
    _Status(429, "rate_limit_error"),
    _Status(500, "internal server error"),
    _Status(529, "overloaded_error"),
    requests.ReadTimeout("read timed out"),
    ValueError("réponse illisible"),
])
def test_errors_that_clear_up_are_not(exc):
    assert not is_fatal(exc)


def test_ollama_not_running_is_fatal_but_a_slow_answer_is_not(monkeypatch):
    provider = OllamaProvider()

    def refused(*_args, **_kwargs):
        raise requests.ConnectionError("[Errno 111] Connection refused")
    monkeypatch.setattr(requests, "post", refused)
    with pytest.raises(ProviderError) as caught:
        provider.generate("système", "texte")
    assert caught.value.fatal

    def slow(*_args, **_kwargs):
        raise requests.ReadTimeout("read timed out")
    monkeypatch.setattr(requests, "post", slow)
    with pytest.raises(ProviderError) as caught:
        provider.generate("système", "texte")
    assert not caught.value.fatal


class KeyRefused(MockProvider):
    """Writes like the mock until its n-th draft, where the key is refused, as it would then be
    for every passage after."""
    name = "essai"
    model = "doublure"

    def __init__(self, refuse_at: int | None = None):
        self.drafts, self.refuse_at, self.current = [], refuse_at, None

    def generate(self, system, user, images=None, meta=None):
        if (meta or {}).get("mode") == "brouillon":
            self.drafts.append(self.current)
            if self.refuse_at == len(self.drafts):
                raise ProviderError("Claude : Error code: 401 - invalid x-api-key", fatal=True)
        return super().generate(system, user, images, meta)


@pytest.fixture()
def run(demo_files, tmp_path, monkeypatch):
    """prepare() on the demo with a given provider; same output folder every time."""
    original = DescriberAgent.describe

    def tracking(self, segment, *args, **kwargs):
        self.provider.current = segment.id
        return original(self, segment, *args, **kwargs)
    monkeypatch.setattr(DescriberAgent, "describe", tracking)

    def go(provider, **options):
        monkeypatch.setattr(pipeline, "get_provider", lambda *a, **k: provider)
        return prepare(demo_files["video"], demo_files["intention"],
                       sous_titres=demo_files["sous_titres"], sortie=tmp_path / "projet",
                       log=lambda _msg: None, **options)
    go.path = tmp_path / "projet" / "projet.json"
    return go


def test_a_refused_key_stops_the_run_and_keeps_what_is_done(run):
    provider = KeyRefused(refuse_at=3)
    with pytest.raises(ProviderError) as caught:
        run(provider)
    message = str(caught.value)
    assert "p003" in message and "--reprendre --refaire-echecs" in message
    assert provider.drafts == ["p001", "p002", "p003"]        # nothing asked after the refusal
    project = load_project(run.path)
    assert [s.etat_ia for s in project.segments] == ["fait", "fait", "echec", "a_faire", "a_faire"]
    assert all(s.brouillon_ia for s in project.segments[:2])
    assert project.preparation_en_cours                      # the editor and the export wait
    stop = project.historique[-1]
    assert stop["action"] == "arret_fournisseur" and stop["passage"] == "p003"
    assert "401" in stop["raison"]


def test_once_fixed_the_run_goes_on_where_it_stopped(run):
    with pytest.raises(ProviderError):
        run(KeyRefused(refuse_at=2))
    provider = KeyRefused()
    run(provider, reprendre=True, refaire_echecs=True)
    assert provider.drafts == ["p002", "p003", "p004", "p005"]   # never p001 again
    project = load_project(run.path)
    assert all(s.etat_ia == "fait" for s in project.segments)
    assert project.preparation["etat"] == "terminee"


def test_an_error_that_clears_up_still_skips_only_its_passage(run):
    """A rate limit or a timeout is not fatal: the run goes on, as before."""
    class Busy(KeyRefused):
        def generate(self, system, user, images=None, meta=None):
            if (meta or {}).get("mode") == "brouillon" and self.current == "p002":
                raise ProviderError("429 Too Many Requests")
            return super().generate(system, user, images, meta)
    run(Busy())
    project = load_project(run.path)
    assert [s.etat_ia for s in project.segments] == ["fait", "echec", "fait", "fait", "fait"]
    assert project.preparation["etat"] == "terminee"


def test_the_command_line_says_what_to_do(demo_files, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "get_provider", lambda *a, **k: KeyRefused(refuse_at=1))
    code = main(["preparer", str(demo_files["video"]), "--intention", str(demo_files["intention"]),
                 "--sous-titres", str(demo_files["sous_titres"]), "--fournisseur", "mock",
                 "--sortie", str(tmp_path / "cle")])
    assert code == 1
    err = capsys.readouterr().err
    assert "Préparation arrêtée" in err and "--reprendre --refaire-echecs" in err

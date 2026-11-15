"""Phase 0 : le journal des appels (appels.jsonl) et la limite de réponse de Claude.

Une ligne par appel au modèle, à côté de projet.json : l'étape, le passage, le modèle, les jetons
tels que l'API les donne (sinon null, jamais estimés), la raison de fin, la durée, le résultat.
Jamais de clé, de consigne ni d'image. Une reprise ne refait aucun appel réussi."""
import importlib.util
import json
import threading

import pytest
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from wasf import pipeline
from wasf.agent import DescriberAgent
from wasf.calllog import CALL_LOG, CallLog, describe_totals, summarize, without_secrets
from wasf.cli import main
from wasf.export import model_calls
from wasf.pipeline import prepare
from wasf.project import load_project
from wasf.providers import (
    CLAUDE_MAX_TOKENS,
    MockProvider,
    ProviderError,
    get_provider,
    unwrapped,
)

FIELDS = {"id", "quand", "etape", "passage", "fournisseur", "modele_demande", "modele_rendu",
          "images", "entree", "jetons_entree", "jetons_sortie", "fin", "essais", "duree_s",
          "statut"}
REPLY = json.dumps({"description": "Amel ouvre la porte.", "confiance": 0.9}, ensure_ascii=False)
IMAGE = b"\xff\xd8\xff\xe0fake-jpeg"


def _lines(folder):
    text = (folder / CALL_LOG).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _prepare(demo_files, out, **options):
    return prepare(demo_files["video"], demo_files["intention"],
                   sous_titres=demo_files["sous_titres"], fournisseur="mock", sortie=out,
                   log=options.pop("log", lambda _msg: None), **options)


# ------------------------------------------------------------------ the log in a real run

def test_one_line_per_call_and_nothing_else(demo_files, tmp_path):
    messages = []
    path = _prepare(demo_files, tmp_path / "projet", log=messages.append)
    project = load_project(path)
    lines = _lines(path.parent)
    calls = model_calls(project)
    assert len(lines) == calls["avec_images"] + calls["texte_seul"] + calls["en_echec"] > 0
    assert [line["id"] for line in lines] == [f"a{i:04d}" for i in range(1, len(lines) + 1)]
    for line in lines:
        assert FIELDS <= set(line)
        assert line["fournisseur"] == "mock" and line["statut"] == "ok"
        assert line["entree"].startswith("sha256:")
        assert line["jetons_entree"] is None and line["jetons_sortie"] is None  # never guessed
    drafts = [line for line in lines if line["etape"] == "brouillon"]
    assert [line["passage"] for line in drafts] == [s.id for s in project.segments]
    images = {s.id: len(s.images) for s in project.segments}
    assert all(line["images"] == images[line["passage"]] for line in drafts)
    assert all(line["images"] == 0 for line in lines if line["etape"] == "revision")
    raw = (path.parent / CALL_LOG).read_text(encoding="utf-8")
    assert project.film not in raw                       # no instructions, no text of the film
    assert any(m.startswith(f"Journal des appels ({CALL_LOG}) : {len(lines)} appel(s), 0 en "
                            "échec") for m in messages)


class Interrupted(MockProvider):
    """Stops like a Ctrl+C at its third draft."""

    def __init__(self):
        self.drafts = 0

    def generate(self, system, user, images=None, meta=None):
        if (meta or {}).get("mode") == "brouillon":
            self.drafts += 1
            if self.drafts == 3:
                raise KeyboardInterrupt
        return super().generate(system, user, images, meta)


def test_a_resumed_run_pays_nothing_twice(demo_files, tmp_path, monkeypatch):
    out = tmp_path / "projet"
    monkeypatch.setattr(pipeline, "get_provider", lambda *args, **kwargs: Interrupted())
    with pytest.raises(KeyboardInterrupt):
        _prepare(demo_files, out)
    first = _lines(out)
    assert first[-1]["statut"] == "interrompu"
    monkeypatch.setattr(pipeline, "get_provider", lambda *args, **kwargs: MockProvider())
    _prepare(demo_files, out, reprendre=True)
    lines = _lines(out)
    assert lines[:len(first)] == first                   # the earlier lines are never rewritten
    assert [line["id"] for line in lines] == [f"a{i:04d}" for i in range(1, len(lines) + 1)]
    written = [line["passage"] for line in lines
               if line["etape"] == "brouillon" and line["statut"] == "ok"]
    assert len(written) == len(set(written)) == len(load_project(out / "projet.json").segments)


def test_a_replaced_project_keeps_its_calls(demo_files, tmp_path):
    out = tmp_path / "projet"
    _prepare(demo_files, out)
    old = (out / CALL_LOG).read_bytes()
    _prepare(demo_files, out, remplacer=True)
    backups = list(out.glob("sauvegarde-*"))
    assert len(backups) == 1 and (backups[0] / CALL_LOG).read_bytes() == old
    assert _lines(out)[0]["id"] == "a0001"


# ------------------------------------------------------------------ the wrapper itself

class Refused(MockProvider):
    name = "anthropic"
    model = "claude-essai"

    def generate(self, system, user, images=None, meta=None):
        cause = RuntimeError("Error code: 401 - invalid x-api-key sk-ant-secret-0123456789")
        cause.status_code = 401
        raise ProviderError(f"Claude : {cause}", fatal=True) from cause


def test_a_failed_call_is_written_down_without_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-0123456789")
    provider = CallLog(tmp_path / CALL_LOG).watch(Refused())
    with pytest.raises(ProviderError):
        provider.generate("système secret", "consigne secrète", [IMAGE],
                          {"mode": "brouillon", "passage": "p001"})
    raw = (tmp_path / CALL_LOG).read_text(encoding="utf-8")
    assert "sk-ant-secret" not in raw and "secrète" not in raw and "système" not in raw
    line = json.loads(raw)
    assert (line["statut"], line["statut_http"], line["fatal"]) == ("erreur", 401, True)
    assert line["passage"] == "p001" and line["images"] == 1 and "***" in line["erreur"]
    assert summarize(tmp_path / CALL_LOG)["echecs"] == 1


def test_keys_are_masked_whatever_their_shape(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ma-cle-gemini-123")
    text = without_secrets("url?key=AIzaSyA0123456789abcdefghij&x=1 ma-cle-gemini-123 sk-abcdefghij")
    assert "AIza" not in text and "ma-cle" not in text and "sk-abc" not in text


def test_the_log_changes_nothing_else(tmp_path):
    inner = MockProvider()
    log = CallLog(tmp_path / CALL_LOG)
    wrapped = log.watch(inner)
    assert log.watch(wrapped) is wrapped and log.watch(None) is None   # never twice
    assert (wrapped.name, wrapped.model) == (inner.name, inner.model)
    assert unwrapped(wrapped) is inner
    agent = DescriberAgent(wrapped, film="Essai", langue="fr")
    assert agent.structured is False                    # a simulation stays a simulation
    wrapped.generate("s", "c", None, {"mode": "brouillon", "passage": "p001"})
    assert wrapped.models_seen == inner.models_seen == {inner.model}


def test_the_totals_read_well(tmp_path):
    log = CallLog(tmp_path / CALL_LOG)
    log.record({"statut": "ok", "jetons_entree": 1200, "jetons_sortie": 80, "duree_s": 2.5,
                "fin": "end_turn"})
    log.record({"statut": "ok", "jetons_entree": None, "jetons_sortie": None, "duree_s": 1.0,
                "fin": "max_tokens"})
    log.record({"statut": "erreur", "duree_s": 0.25})
    totals = summarize(tmp_path / CALL_LOG)
    assert (totals["appels"], totals["echecs"], totals["coupees"]) == (3, 1, 1)
    assert (totals["jetons_entree"], totals["jetons_sortie"]) == (1200, 80)
    assert describe_totals(totals) == (
        "Journal des appels (appels.jsonl) : 3 appel(s), 1 en échec, 3,8 s d'attente, 1200 jetons "
        "envoyés et 80 reçus sur 1 appel(s) ; 2 appel(s) sans compte de jetons ; 1 réponse(s) "
        "coupée(s) par la limite de longueur.")


# ------------------------------------------------------------------ what each API says

@pytest.fixture(scope="module")
def api():
    app = Flask("api")
    seen: dict = {}

    @app.post("/v1/messages")
    def anthropic_messages():
        seen["anthropic"] = request.get_json()
        return jsonify({"id": "msg_1", "type": "message", "role": "assistant",
                        "model": "claude-rendu", "content": [{"type": "text", "text": REPLY}],
                        "stop_reason": "max_tokens", "stop_sequence": None,
                        "usage": {"input_tokens": 1534, "output_tokens": 1024}})

    @app.post("/v1/chat/completions")
    def openai_chat():
        return jsonify({"id": "c1", "object": "chat.completion", "created": 0, "model": "gpt-rendu",
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": REPLY}}],
                        "usage": {"prompt_tokens": 812, "completion_tokens": 96,
                                  "total_tokens": 908}})

    @app.post("/api/chat")
    def ollama_chat():
        return jsonify({"model": "gemma3:rendu", "done": True, "done_reason": "stop",
                        "prompt_eval_count": 640, "eval_count": 88,
                        "message": {"role": "assistant", "content": REPLY}})

    @app.post("/v1/models/<path:rest>")
    @app.post("/v1beta/models/<path:rest>")
    def gemini_generate(rest):
        return jsonify({"candidates": [{"content": {"role": "model", "parts": [{"text": REPLY}]},
                                        "finishReason": "STOP", "index": 0}],
                        "modelVersion": "gemini-rendu",
                        "usageMetadata": {"promptTokenCount": 1290, "candidatesTokenCount": 75,
                                          "totalTokenCount": 1365}})

    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, "test-key")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def _needs(module):
    return pytest.mark.skipif(importlib.util.find_spec(module) is None, reason=f"{module} absent")


def _one_call(provider, folder):
    CallLog(folder / CALL_LOG).watch(provider).generate(
        "système", "consigne", [IMAGE], {"mode": "brouillon", "passage": "p001"})
    return _lines(folder)[0]


@_needs("anthropic")
def test_claude_tokens_and_a_cut_answer(api, tmp_path):
    url, seen = api
    notes: list[str] = []
    provider = get_provider("anthropic", "claude-essai", url)
    provider.notify = notes.append
    line = _one_call(provider, tmp_path)
    assert seen["anthropic"]["max_tokens"] == CLAUDE_MAX_TOKENS == 1024   # was 400
    assert (line["jetons_entree"], line["jetons_sortie"], line["fin"]) == (1534, 1024, "max_tokens")
    assert line["modele_rendu"] == "claude-rendu" and line["essais"] is None
    assert notes and "réponse coupée à 1024 jetons" in notes[0]
    assert summarize(tmp_path / CALL_LOG)["coupees"] == 1


@_needs("anthropic")
def test_the_claude_limit_can_be_changed(api):
    url, seen = api
    get_provider("anthropic", "claude-essai", url, max_tokens=2048).generate("s", "c")
    assert seen["anthropic"]["max_tokens"] == 2048
    with pytest.raises(ProviderError, match="--jetons-max"):
        get_provider("anthropic", "claude-essai", url, max_tokens=0)


@_needs("openai")
def test_openai_tokens(api, tmp_path):
    url, _seen = api
    line = _one_call(get_provider("openai", "gpt-essai", f"{url}/v1"), tmp_path)
    assert (line["jetons_entree"], line["jetons_sortie"], line["fin"]) == (812, 96, "stop")
    assert line["modele_rendu"] == "gpt-rendu"


def test_ollama_tokens(api, tmp_path):
    url, _seen = api
    line = _one_call(get_provider("ollama", "gemma3", url), tmp_path)
    assert (line["jetons_entree"], line["jetons_sortie"], line["fin"]) == (640, 88, "stop")
    assert line["modele_rendu"] == "gemma3:rendu" and line["essais"] == 1


@_needs("google.genai")
def test_gemini_tokens(api, tmp_path):
    url, _seen = api
    line = _one_call(get_provider("gemini", "gemini-essai", url), tmp_path)
    assert (line["jetons_entree"], line["jetons_sortie"], line["fin"]) == (1290, 75, "STOP")
    assert line["modele_rendu"] == "gemini-rendu" and line["essais"] == 1


def test_the_command_line_passes_the_limit_on(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr("wasf.cli.prepare", lambda *args, **kwargs: seen.update(kwargs) or tmp_path)
    assert main(["preparer", "film.mp4", "--intention", "i.yaml", "--fournisseur", "anthropic",
                 "--jetons-max", "1500"]) == 0
    assert seen["jetons_max"] == 1500

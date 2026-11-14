"""Check the exact requests sent to each AI provider, against a local fake server.

No network and no API key needed: every SDK is pointed at 127.0.0.1.
"""
import importlib.util
import json
import threading
import time

import pytest
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from wasf import providers
from wasf.prompts import parse_reply
from wasf.providers import DEFAULT_MODELS, ProviderError, get_provider

REPLY = json.dumps({"description": "Amel ouvre la porte.", "confiance": 0.9}, ensure_ascii=False)
IMAGE = b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.fixture(scope="module")
def fake_server():
    app = Flask("fake")
    seen: dict = {}

    @app.post("/v1/messages")
    def anthropic_messages():
        seen["anthropic"] = request.get_json()
        return jsonify({"id": "msg_1", "type": "message", "role": "assistant", "model": "m",
                        "content": [{"type": "text", "text": REPLY}], "stop_reason": "end_turn",
                        "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})

    @app.post("/v1/chat/completions")
    def openai_chat():
        seen["openai"] = request.get_json()
        return jsonify({"id": "c1", "object": "chat.completion", "created": 0, "model": "m",
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": REPLY}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    @app.post("/api/chat")
    def ollama_chat():
        seen["ollama"] = request.get_json()
        return jsonify({"model": "m", "done": True, "message": {"role": "assistant", "content": REPLY}})

    @app.post("/v1/models/<path:rest>")
    @app.post("/v1beta/models/<path:rest>")
    def gemini_generate(rest):
        model = rest.split(":")[0]
        calls = seen.setdefault("calls", {})
        calls[model] = calls.get(model, 0) + 1
        # Google's own format for « too many requests »: which quota, and how long to wait.
        if model == "gemini-day" or (model == "gemini-minute" and calls[model] == 1):
            quota = ("GenerateRequestsPerDayPerProjectPerModel-FreeTier" if model == "gemini-day"
                     else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier")
            return jsonify({"error": {
                "code": 429, "status": "RESOURCE_EXHAUSTED",
                "message": "You exceeded your current quota. Please retry in 23.4s.",
                "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                             "violations": [{"quotaId": quota, "quotaValue": "5"}]},
                            {"@type": "type.googleapis.com/google.rpc.RetryInfo",
                             "retryDelay": "23s"}]}}), 429
        if model == "gemini-busy" and calls[model] == 1:
            return jsonify({"error": {"code": 503, "status": "UNAVAILABLE",
                                      "message": "This model is currently experiencing high "
                                                 "demand. Please try again later."}}), 503
        if model == "gemini-slow":
            time.sleep(3)
        seen["gemini"] = {"path": rest, "body": request.get_json()}
        return jsonify({"candidates": [{"content": {"role": "model", "parts": [{"text": REPLY}]},
                                        "finishReason": "STOP", "index": 0}],
                        "modelVersion": "gemini-routed-001",
                        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1,
                                          "totalTokenCount": 2}})

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


def test_default_models_are_current():
    # gemini-3.5-flash is deprecated and routed to 3.6; OpenAI removes gpt-4o-mini in January 2027.
    assert DEFAULT_MODELS["gemini"] == "gemini-3.6-flash"
    assert DEFAULT_MODELS["openai"] == "gpt-6-luna"


@_needs("anthropic")
def test_anthropic_request(fake_server):
    url, seen = fake_server
    provider = get_provider("anthropic", "claude-test", url)
    text = provider.generate("système", "consigne", [IMAGE])
    assert parse_reply(text)["description"] == "Amel ouvre la porte."
    assert provider.models_seen == {"m"}  # the model the API says answered
    body = seen["anthropic"]
    assert body["model"] == "claude-test" and body["system"] == "système"
    blocks = body["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/jpeg"
    assert blocks[-1] == {"type": "text", "text": "consigne"}


@_needs("openai")
def test_openai_request(fake_server):
    url, seen = fake_server
    provider = get_provider("openai", "gpt-test", f"{url}/v1")
    text = provider.generate("système", "consigne", [IMAGE])
    assert parse_reply(text)["confiance"] == 0.9
    content = seen["openai"]["messages"][1]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert seen["openai"]["temperature"] == 0.4  # a local server gets a temperature...
    assert provider.models_seen == {"m"}
    # ...OpenAI's own API does not: its recent reasoning models may refuse the parameter.
    assert get_provider("openai", None, "https://api.openai.com/v1")._send_temperature is False


def test_ollama_request(fake_server):
    url, seen = fake_server
    provider = get_provider("ollama", "gemma3", url)
    text = provider.generate("système", "consigne", [IMAGE])
    assert parse_reply(text)["description"] == "Amel ouvre la porte."
    body = seen["ollama"]
    assert body["format"] == "json" and body["stream"] is False
    assert len(body["messages"][1]["images"]) == 1
    assert provider.models_seen == {"m"}


@_needs("google.genai")
def test_gemini_request(fake_server):
    url, seen = fake_server
    provider = get_provider("gemini", "gemini-test", url)
    text = provider.generate("système", "consigne", [IMAGE])
    assert parse_reply(text)["description"] == "Amel ouvre la porte."
    assert seen["gemini"]["path"] == "gemini-test:generateContent"
    body = seen["gemini"]["body"]
    assert "temperature" not in body.get("generationConfig", {})  # Gemini 3 ignores it
    assert provider.models_seen == {"gemini-routed-001"}  # the model Google says answered
    parts = body["contents"][0]["parts"]
    inline = parts[0]["inlineData"]
    assert (inline.get("mimeType") or inline.get("mime_type")) == "image/jpeg"
    assert parts[-1]["text"] == "consigne"
    assert body["systemInstruction"]["parts"][0]["text"] == "système"


@_needs("google.genai")
def test_gemini_waits_out_a_per_minute_limit(fake_server, monkeypatch):
    url, seen = fake_server
    waits, notes = [], []
    monkeypatch.setattr(providers, "_wait", waits.append)
    provider = get_provider("gemini", "gemini-minute", url)
    provider.notify = notes.append
    text = provider.generate("système", "consigne", [IMAGE])
    assert parse_reply(text)["description"] == "Amel ouvre la porte."
    assert waits == [24.0] and seen["calls"]["gemini-minute"] == 2  # Google asked for 23 s
    assert "nouvel essai dans 24 s" in notes[0]


@_needs("google.genai")
def test_gemini_does_not_wait_when_the_days_quota_is_used_up(fake_server, monkeypatch):
    url, seen = fake_server
    waits: list[float] = []
    monkeypatch.setattr(providers, "_wait", waits.append)
    provider = get_provider("gemini", "gemini-day", url)
    with pytest.raises(ProviderError, match="quota gratuit du jour"):
        provider.generate("système", "consigne", [IMAGE])
    assert waits == [] and seen["calls"]["gemini-day"] == 1


@_needs("google.genai")
def test_a_stalled_gemini_request_gives_up(fake_server, monkeypatch):
    url, _seen = fake_server
    monkeypatch.setattr(providers, "REQUEST_TIMEOUT", 1)
    provider = get_provider("gemini", "gemini-slow", url)
    start = time.monotonic()
    with pytest.raises(ProviderError, match="pas de réponse en 1 s"):
        provider.generate("système", "consigne", [IMAGE])
    assert time.monotonic() - start < 2.9  # the fake server answers after 3 s


@_needs("google.genai")
def test_gemini_waits_when_googles_servers_are_busy(fake_server, monkeypatch):
    # A real run: « 503 UNAVAILABLE, this model is currently experiencing high demand ».
    url, seen = fake_server
    waits, notes = [], []
    monkeypatch.setattr(providers, "_wait", waits.append)
    provider = get_provider("gemini", "gemini-busy", url)
    provider.notify = notes.append
    assert parse_reply(provider.generate("système", "consigne", [IMAGE]))["description"]
    assert waits == [10.0] and seen["calls"]["gemini-busy"] == 2
    assert "serveurs de Google surchargés" in notes[0]

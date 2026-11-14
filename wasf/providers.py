"""Vision-language model providers.

All providers expose the same method:
    generate(system, user, images, meta) -> str (the raw model reply)

- mock      : offline simulation, no AI call (tests, demos without a key)
- gemini    : Google Gemini API      (pip install google-genai, GEMINI_API_KEY)
- anthropic : Claude API             (pip install anthropic, ANTHROPIC_API_KEY)
- openai    : OpenAI or any OpenAI-compatible server (pip install openai, OPENAI_API_KEY)
- ollama    : local model, images never leave the computer (https://ollama.com)

Models are chosen with --modele or the WASF_<PROVIDER>_MODEL variables;
check each provider's model list, names change often.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time

import requests

PROVIDERS = ("mock", "gemini", "anthropic", "openai", "ollama")

DEFAULT_MODELS = {
    "gemini": "gemini-3.6-flash",     # gemini-3.5-flash is deprecated and routed to 3.6
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-6-luna",           # OpenAI removes gpt-4o-mini on 14 January 2027
    "ollama": "gemma3",
}


class ProviderError(RuntimeError):
    """The provider is not installed, not configured, or returned an error.

    fatal: the same error would come back for every passage (key refused, unknown model, the
    day's quota or the account's credit used up, local server not running). Preparation then
    stops at once instead of failing every passage one after the other (see is_fatal)."""

    def __init__(self, message: str = "", *, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


# Errors that no later passage can escape. Rate limits per minute, busy servers and timeouts
# are not among them: they clear up, and the passage can be redone with --refaire-echecs.
FATAL_STATUS = {401, 403, 404}   # key refused, access denied, unknown model or address
FATAL_MARKERS = ("PerDay",                                  # Gemini: the day's quota is used up
                 "API_KEY_INVALID", "API key not valid",    # Gemini: wrong key (sent as a 400)
                 "insufficient_quota",                      # OpenAI: no credit left
                 "credit balance")                          # Claude: no credit left


def _status(exc: BaseException) -> int | None:
    """The HTTP status of an SDK or requests error, when it carries one."""
    for value in (getattr(exc, "status_code", None), getattr(exc, "code", None),
                  getattr(getattr(exc, "response", None), "status_code", None)):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def is_fatal(exc: BaseException) -> bool:
    """True when trying the next passage would only meet the same error: a refused key, an
    unknown model, an exhausted daily quota or credit, or a local server (Ollama) that does not
    answer at all. Read from the HTTP status and from the providers' own error codes."""
    if isinstance(exc, requests.ConnectionError):
        return True
    if _status(exc) in FATAL_STATUS:
        return True
    text = str(exc)
    return any(marker in text for marker in FATAL_MARKERS)


class Provider:
    name = "base"
    model = ""  # the model asked for

    def generate(self, system: str, user: str, images: list[bytes] | None = None,
                 meta: dict | None = None) -> str:
        raise NotImplementedError

    @property
    def models_seen(self) -> set[str]:
        """The models the API says actually answered: a provider can reroute a retired name,
        and the transparency report must name the model that wrote the text."""
        return self.__dict__.setdefault("_models_seen", set())

    def _saw(self, model_name) -> None:
        if model_name:
            self.models_seen.add(str(model_name))

    def notify(self, message: str) -> None:
        """Tell the person running Wasf what is happening (the pipeline sends it to its log)."""
        print(message, flush=True)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# --------------------------------------------------------------------------- mock
FILLERS = {
    "fr": "La caméra reste fixe et la lumière ne change pas pendant tout le plan.",
    "ar": "تبقى الكاميرا ثابتة ولا يتغير الضوء طوال اللقطة.",
    "aeb": "الكاميرا تبقى ثابتة والضو ما يتبدّلش طول اللقطة.",
}


_DANGLING = {"au", "aux", "du", "des", "de", "d'", "la", "le", "les", "l'", "un", "une", "et",
             "sur", "vers", "jusqu'au", "jusqu'à", "puis", "dans", "en", "à", "avec", "pour",
             "par", "qui", "que", "في", "على", "إلى", "من", "ثم", "و", "مع"}


def _shorten(text: str, budget: int) -> str:
    """Keep whole sentences when possible, never end on a dangling little word."""
    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?؟])\s+", text.strip()):
        if len(" ".join(kept + [sentence]).split()) > budget:
            break
        kept.append(sentence)
    if kept:
        return " ".join(kept)
    words = text.split()[:budget]
    while len(words) > 1 and words[-1].strip(",;:.").lower() in _DANGLING:
        words.pop()
    out = " ".join(words).rstrip(",;:")
    return out if out.endswith((".", "!", "?", "؟")) else out + "."


class MockProvider(Provider):
    """Deterministic stand-in for a real model. It does not look at the images:
    it rewrites the director's notes, so the whole pipeline can be tested offline."""

    name = "mock"
    model = "simulation-hors-ligne"

    def generate(self, system, user, images=None, meta=None):
        self._saw(self.model)
        meta = meta or {}
        langue = meta.get("langue", "fr")
        budget = int(meta.get("budget", 12))
        if meta.get("mode") == "revision":
            text = meta.get("brouillon", "")
            for phrase in meta.get("a_eviter", []):
                text = re.sub(re.escape(phrase), "", text, flags=re.I)
            short = _shorten(" ".join(text.split()), budget)
            # Like a real model asked for it: less sure when the director's note had to be cut.
            note = len((meta.get("a_remarquer") or short).split()) or 1
            kept = min(1.0, len(short.split()) / note)
            confidence = 0.8 if kept >= 0.99 else round(0.3 + 0.5 * kept, 2)
            remark = ("Simulation : description coupée pour tenir dans la pause." if kept < 0.99
                      else "Simulation : aucune image n'a été analysée.")
            return json.dumps({"description": short, "confiance": confidence, "remarque": remark},
                              ensure_ascii=False)
        base = (meta.get("a_remarquer") or "").strip()
        text = f"{base} {FILLERS[langue]}".strip() if base else FILLERS[langue]
        return json.dumps({"description": text, "confiance": 0.6,
                           "remarque": "Simulation : aucune image n'a été analysée."},
                          ensure_ascii=False)


# --------------------------------------------------------------------------- gemini
REQUEST_TIMEOUT = 120      # seconds: a stalled request fails instead of holding up the whole run
RATE_LIMIT_RETRIES = 2     # waits on a per-minute limit before the passage is given up
BUSY_WAIT = 10.0          # first wait when Google's servers are busy, then twice as long
MAX_WAIT = 65.0            # a per-minute limit clears within the minute


def _wait(seconds: float) -> None:
    time.sleep(seconds)


def _retry_wait(exc: Exception, attempt: int) -> tuple[float, str] | None:
    """How long to wait before trying again, and why; None when waiting cannot help: another
    error, or the day's quota is used up."""
    text, code = str(exc), getattr(exc, "code", None)
    if code == 429 or "RESOURCE_EXHAUSTED" in text:
        if "PerDay" in text:
            return None
        found = (re.search(r"retryDelay['\"]?\s*:\s*['\"]?([\d.]+)s", text)
                 or re.search(r"retry in ([\d.]+)\s*s", text, re.IGNORECASE))
        seconds = min(MAX_WAIT, float(found.group(1)) + 1.0) if found else 30.0
        return seconds, "trop de requêtes pour cette minute"
    # « This model is currently experiencing high demand »: Google says it is usually brief.
    if code in (500, 502, 503, 504) or "UNAVAILABLE" in text:
        return BUSY_WAIT * (attempt + 1), "serveurs de Google surchargés"
    return None


def _gemini_error(exc: Exception) -> str:
    text = str(exc)
    if "PerDay" in text and (getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in text):
        return ("Gemini : quota gratuit du jour épuisé. Reprenez demain, prenez une offre "
                "payante, ou utilisez --fournisseur ollama.")
    if "Timeout" in type(exc).__name__:
        return (f"Gemini : pas de réponse en {REQUEST_TIMEOUT} s (connexion lente ou coupée ?). "
                "Le passage reste à écrire ; relancez plus tard pour réessayer.")
    return f"Gemini : {exc}"


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model: str | None = None, base_url: str | None = None):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ProviderError("Le fournisseur « gemini » nécessite : pip install google-genai") from exc
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ProviderError("Définissez la variable GEMINI_API_KEY (clé Google AI Studio).")
        self._types = types
        # Without a timeout the SDK waits forever on a stalled connection.
        options = types.HttpOptions(timeout=REQUEST_TIMEOUT * 1000,
                                    **({"base_url": base_url} if base_url else {}))
        self.client = genai.Client(api_key=key, http_options=options)
        self.model = model or os.environ.get("WASF_GEMINI_MODEL", DEFAULT_MODELS["gemini"])

    def generate(self, system, user, images=None, meta=None):
        types = self._types
        parts = [types.Part.from_bytes(data=img, mime_type="image/jpeg") for img in images or []]
        parts.append(user)
        # No temperature: Google asks to remove it for Gemini 3 models, which ignore it.
        config = types.GenerateContentConfig(system_instruction=system,
                                             response_mime_type="application/json")
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                response = self.client.models.generate_content(model=self.model, contents=parts,
                                                               config=config)
                break
            except Exception as exc:  # network, quota, timeout, wrong model name…
                retry = _retry_wait(exc, attempt) if attempt < RATE_LIMIT_RETRIES else None
                if retry is None:
                    raise ProviderError(_gemini_error(exc), fatal=is_fatal(exc)) from exc
                seconds, why = retry
                self.notify(f"Gemini : {why}, nouvel essai dans {round(seconds)} s…")
                _wait(seconds)
        self._saw(getattr(response, "model_version", None))
        return response.text or ""


# --------------------------------------------------------------------------- anthropic
class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str | None = None, base_url: str | None = None):
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError("Le fournisseur « anthropic » nécessite : pip install anthropic") from exc
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ProviderError("Définissez la variable ANTHROPIC_API_KEY.")
        kwargs = {"base_url": base_url} if base_url else {}
        self.client = anthropic.Anthropic(**kwargs)
        self.model = model or os.environ.get("WASF_ANTHROPIC_MODEL", DEFAULT_MODELS["anthropic"])

    def generate(self, system, user, images=None, meta=None):
        content = [{"type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(img)}}
                   for img in images or []]
        content.append({"type": "text", "text": user})
        try:
            message = self.client.messages.create(
                model=self.model, max_tokens=400, system=system,
                messages=[{"role": "user", "content": content}])
        except Exception as exc:
            raise ProviderError(f"Claude : {exc}", fatal=is_fatal(exc)) from exc
        self._saw(getattr(message, "model", None))
        return "".join(getattr(block, "text", "") for block in message.content)


# --------------------------------------------------------------------------- openai
class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, model: str | None = None, base_url: str | None = None):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError("Le fournisseur « openai » nécessite : pip install openai") from exc
        if not os.environ.get("OPENAI_API_KEY") and not base_url:
            raise ProviderError("Définissez la variable OPENAI_API_KEY "
                                "(ou --url pour un serveur compatible local).")
        kwargs = {"base_url": base_url} if base_url else {}
        if base_url and not os.environ.get("OPENAI_API_KEY"):
            kwargs["api_key"] = "local"
        self.client = OpenAI(**kwargs)
        self.model = model or os.environ.get("WASF_OPENAI_MODEL", DEFAULT_MODELS["openai"])
        # A temperature for local or compatible servers only: OpenAI's recent reasoning
        # models may refuse the parameter.
        self._send_temperature = bool(base_url) and "api.openai.com" not in base_url

    def generate(self, system, user, images=None, meta=None):
        content = [{"type": "text", "text": user}]
        content += [{"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{_b64(img)}"}}
                    for img in images or []]
        options = {"temperature": 0.4} if self._send_temperature else {}
        try:
            response = self.client.chat.completions.create(
                model=self.model, **options,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": content}])
        except Exception as exc:
            raise ProviderError(f"OpenAI : {exc}", fatal=is_fatal(exc)) from exc
        self._saw(getattr(response, "model", None))
        return response.choices[0].message.content or ""


# --------------------------------------------------------------------------- ollama
class OllamaProvider(Provider):
    """Local model: frames never leave the computer (best option for unreleased films)."""

    name = "ollama"

    def __init__(self, model: str | None = None, base_url: str | None = None):
        host = base_url or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        if not host.startswith("http"):
            host = "http://" + host
        self.base_url = host.replace("0.0.0.0", "127.0.0.1").rstrip("/")
        self.model = model or os.environ.get("WASF_OLLAMA_MODEL", DEFAULT_MODELS["ollama"])

    def generate(self, system, user, images=None, meta=None):
        payload = {
            "model": self.model, "stream": False, "format": "json",
            "options": {"temperature": 0.4},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user,
                          "images": [_b64(img) for img in images or []]}],
        }
        try:
            response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=600)
            response.raise_for_status()
            data = response.json()
            self._saw(data.get("model"))
            return data["message"]["content"]
        except requests.RequestException as exc:
            raise ProviderError(f"Ollama ({self.base_url}) : {exc}. "
                                f"Lancez « ollama pull {self.model} » puis « ollama serve ».",
                                fatal=is_fatal(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise ProviderError(f"Ollama : réponse inattendue ({exc}).") from exc


def get_provider(name: str, model: str | None = None, base_url: str | None = None) -> Provider:
    name = (name or "mock").lower()
    if name == "mock":
        return MockProvider()
    if name == "gemini":
        return GeminiProvider(model, base_url)
    if name in ("anthropic", "claude"):
        return AnthropicProvider(model, base_url)
    if name == "openai":
        return OpenAIProvider(model, base_url)
    if name == "ollama":
        return OllamaProvider(model, base_url)
    raise ProviderError(f"Fournisseur inconnu : {name}. Choisir parmi : {', '.join(PROVIDERS)}.")

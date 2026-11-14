"""Voices for the descriptions.

Engines:
- humain : recordings made by the describer (recommended for Derja and for the final film)
- azure  : Azure AI Speech, incl. Tunisian voices ar-TN-ReemNeural / ar-TN-HediNeural
- espeak : espeak-ng, offline and free, robotic but fine for working versions
- piper  : Piper, offline neural voices (check each voice's licence)
- bip    : a placeholder tone, only for tests
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import numpy as np

from . import media

ENGINES = ("humain", "azure", "espeak", "piper", "bip")
WORDS_PER_SECOND = {"fr": 2.5, "ar": 2.0, "aeb": 2.2}
AZURE_VOICES = {"fr": "fr-FR-DeniseNeural", "ar": "ar-TN-ReemNeural", "aeb": "ar-TN-ReemNeural"}
ESPEAK_VOICES = {"fr": "fr", "ar": "ar", "aeb": "ar"}
RECORDING_EXTENSIONS = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".opus")


class TTSError(RuntimeError):
    """The voice could not be produced."""


# What a team can say about the recordings it supplies (engine « humain »). Wasf cannot check
# it, so it keeps it as the team's declaration, never as something it verified.
VOICE_SOURCES = {"humaine": "voix humaines", "synthese": "voix de synthèse",
                 "inconnue": "origine inconnue"}


def declared_source(source: str | None, par: str | None) -> dict:
    """The team's declaration about the recordings it supplied: human voices, synthetic voices
    made elsewhere, or unknown; and who lent their voice (with their consent) or which tool
    made them. Recorded as said, marked as not verified."""
    if source and source not in VOICE_SOURCES:
        raise TTSError(f"Source de voix inconnue : {source}. Choisir parmi : "
                       f"{', '.join(VOICE_SOURCES)}.")
    return {"source": source or "non_declaree", "par": (par or "").strip() or None,
            "verifiee_par_wasf": False,
            "remarque": ("déclaration de l'équipe, non vérifiée par Wasf" if source
                         else "l'équipe n'a pas déclaré l'origine des enregistrements")}


def describe_voice(engine: str, voix: str | None, langue: str, source: str | None = None,
                   par: str | None = None) -> dict:
    """Who speaks the descriptions, for the transparency report and the credits: a person, a
    synthetic voice (which one, from which service) or a test signal. Names only: never a
    path from this computer. source and par: the team's declaration about supplied recordings
    (engine « humain » only, see declared_source)."""
    if engine == "humain":   # Wasf cannot tell who or what made the files: it says so
        return {"type": "enregistrements_fournis", "moteur": engine,
                "libelle": "enregistrements fournis par l'équipe (moteur « humain »), "
                           "sans synthèse vocale par Wasf",
                "declaration": declared_source(source, par)}
    if engine == "bip":
        return {"type": "signal_de_test", "moteur": engine,
                "libelle": "signal de test, pas une voix (essai technique)"}
    if engine == "azure":
        name = voix or AZURE_VOICES.get(langue, AZURE_VOICES["fr"])
        return {"type": "voix_de_synthese", "moteur": engine, "voix": name,
                "service": "Azure AI Speech", "sur_cet_ordinateur": False,
                "libelle": f"voix de synthèse {name} (Azure AI Speech)"}
    if engine == "espeak":
        name = voix or ESPEAK_VOICES.get(langue, "fr")
        return {"type": "voix_de_synthese", "moteur": engine, "voix": name,
                "service": "espeak-ng", "sur_cet_ordinateur": True,
                "libelle": f"voix de synthèse espeak-ng ({name}), sur cet ordinateur"}
    if engine == "piper":
        name = Path(voix).name if voix else ""
        return {"type": "voix_de_synthese", "moteur": engine, "voix": name, "service": "Piper",
                "sur_cet_ordinateur": True,
                "libelle": f"voix de synthèse Piper ({name}), sur cet ordinateur"}
    return {"type": "inconnu", "moteur": engine, "libelle": f"moteur « {engine} »"}


def speaking_rate(langue: str, rate: float | None = None) -> float:
    """Words per second behind the word budgets: the director's, else the language's."""
    return float(rate) if rate else WORDS_PER_SECOND.get(langue, 2.5)


def estimated_seconds(text: str, langue: str, rate: float | None = None) -> float:
    """How long a text should take to say, at that rate. An estimate: the real voice is only
    timed when the track is exported."""
    return len((text or "").split()) / speaking_rate(langue, rate)


def synthesize(engine: str, text: str, out_wav: Path, *, langue: str, voix: str | None = None,
               segment_id: str = "", enregistrements: Path | None = None,
               sample_rate: int = 48000) -> Path:
    """Write a mono WAV at sample_rate with the spoken text."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if engine == "humain":
        return media.to_wav(_recording(enregistrements, segment_id), out_wav, sample_rate, 1)

    raw = out_wav.with_name(out_wav.stem + ".brut.wav")
    if engine == "bip":
        _tone(text, raw, langue)
    elif engine == "espeak":
        _espeak(text, raw, langue, voix)
    elif engine == "piper":
        _piper(text, raw, voix)
    elif engine == "azure":
        _azure(text, raw, langue, voix)
    else:
        raise TTSError(f"Moteur de voix inconnu : {engine}. Choisir parmi : {', '.join(ENGINES)}.")
    if not raw.exists() or raw.stat().st_size < 100:
        raise TTSError(f"Le moteur « {engine} » n'a produit aucun son.")
    media.to_wav(raw, out_wav, sample_rate, 1)
    raw.unlink(missing_ok=True)
    return out_wav


def _tone(text: str, path: Path, langue: str, sample_rate: int = 22050) -> None:
    """Placeholder 'voice': a soft tone lasting as long as the text would take to read."""
    seconds = max(0.6, len(text.split()) / WORDS_PER_SECOND.get(langue, 2.5))
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    syllables = 0.55 + 0.45 * np.abs(np.sin(np.pi * 4.0 * t))
    tone = (0.6 * np.sin(2 * np.pi * 196 * t) + 0.4 * np.sin(2 * np.pi * 392 * t)) * syllables
    fade = np.minimum(1.0, np.minimum(t, seconds - t) / 0.05)
    media.write_wav(path, (0.25 * tone * fade).astype(np.float32), sample_rate)


def _espeak(text: str, path: Path, langue: str, voix: str | None) -> None:
    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    if not binary:
        raise TTSError("espeak-ng est introuvable. Linux : sudo apt install espeak-ng ; "
                       "macOS : brew install espeak-ng ; Windows : installeur sur "
                       "https://github.com/espeak-ng/espeak-ng/releases")
    media.run([binary, "-v", voix or ESPEAK_VOICES.get(langue, "fr"), "-s", "160",
               "-w", str(path), "--stdin"], input_text=text)


def _piper(text: str, path: Path, voix: str | None) -> None:
    if not voix:
        raise TTSError("Piper : indiquez le modèle de voix avec --voix chemin/voix.onnx. "
                       "Vérifiez la licence de chaque voix : beaucoup sont réservées à un usage "
                       "non commercial.")
    binary = shutil.which("piper")
    command = [binary] if binary else [sys.executable, "-m", "piper"]
    media.run(command + ["--model", str(voix), "--output_file", str(path)], input_text=text)


def _azure(text: str, path: Path, langue: str, voix: str | None) -> None:
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError as exc:
        raise TTSError("Le moteur « azure » nécessite : pip install azure-cognitiveservices-speech") from exc
    key, region = os.environ.get("AZURE_SPEECH_KEY"), os.environ.get("AZURE_SPEECH_REGION")
    if not key or not region:
        raise TTSError("Définissez AZURE_SPEECH_KEY et AZURE_SPEECH_REGION.")
    config = speechsdk.SpeechConfig(subscription=key, region=region)
    config.speech_synthesis_voice_name = voix or AZURE_VOICES.get(langue, AZURE_VOICES["fr"])
    audio = speechsdk.audio.AudioOutputConfig(filename=str(path))
    result = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=audio) \
        .speak_text_async(text).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = getattr(result, "cancellation_details", None)
        raise TTSError(f"Azure : synthèse impossible ({getattr(details, 'error_details', result.reason)}).")


def find_recording(folder: Path | None, segment_id: str) -> Path | None:
    """The recording of one passage: p001.wav, else p001.mp3, p001.m4a… in that order, whatever
    the case of the name (P001.M4A from a phone counts too). None when there is none."""
    if not folder or not Path(folder).is_dir():
        return None
    files = {p.name.lower(): p for p in Path(folder).iterdir() if p.is_file()}
    for ext in RECORDING_EXTENSIONS:
        found = files.get(f"{segment_id}{ext}".lower())
        if found is not None:
            return found
    return None


def _recording(folder: Path | None, segment_id: str) -> Path:
    if not folder:
        raise TTSError("Moteur « humain » : indiquez le dossier des enregistrements avec --enregistrements.")
    if not Path(folder).is_dir():
        raise TTSError(f"Dossier des enregistrements introuvable : {folder}")
    found = find_recording(folder, segment_id)
    if found is None:
        raise TTSError(f"Enregistrement manquant : {segment_id}.wav (ou .mp3, .m4a…) dans {folder}")
    return found

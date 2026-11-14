"""Place each spoken description in its pause and lower the film's sound underneath.

The film's sound is mixed a slice at a time (MIX_CHUNK_SECONDS) and written to the output
files as it goes, so memory no longer grows with the length of the film. The result is the
same, sample for sample, as mixing the whole film at once: every sample goes through the same
operations, and the loudness check (a single gain for the whole film when it would clip) is
measured over the whole film before that gain is applied.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from . import media
from .tts import estimated_seconds, synthesize

MIX_CHUNK_SECONDS = 30.0   # a slice of the film mixed at a time (about 20 MB of samples)
PEAK_LIMIT = 0.98          # above this, the whole mix is turned down by one gain
OVERRUN_TOLERANCE = 0.05   # seconds a voice may run past its pause before it counts as too long

# Voice checks (lot 2). Measured on each voice as it comes from the engine or the recording,
# before it is sped up; never on the film, whose own silences and music would raise false alarms.
FRAME_SECONDS = 0.02       # speech is looked for in 20 ms frames...
SPEECH_DB = -45.0          # ...louder than this (a phone's background noise stays below)
SILENT_PEAK_DB = -40.0     # a voice that never gets this loud cannot be heard: blocks
CLIP_LEVEL = 32440         # 99 % of full scale, in 16-bit samples...
CLIP_RUN = 3               # ...held for 3 samples or more: a flattened, clipped peak
CLIP_ALERT = 3             # a warning from 3 clipped peaks
LEVEL_GAP_DB = 6.0         # speech this much louder or quieter than the median voice: warning
SHORT_RATIO = 0.4          # speech under 40 % of the time its text needs: wrong or cut file?
SHORT_MIN_TEXT = 1.0       # (only for texts that need at least 1 s)
EDGE_SILENCE = 1.0         # more silence than this before or after the speech: warning
TRIM_MARGIN = 0.08         # silence kept on each side when --couper-silences trims a voice
FLOOR_DB = -120.0          # how digital silence is written (no -inf in JSON)
BLOCKING = "bloquant"
WARNING = "alerte"


def _s(seconds: float) -> str:
    return f"{seconds:.1f}".replace(".", ",")


def _db(value: float) -> float:
    return round(float(20 * np.log10(value)), 1) if value > 0 else FLOOR_DB


def _speech(samples: np.ndarray, sample_rate: int) -> tuple[int, int, float] | None:
    """Where the speech is in a 16-bit voice: (first sample, one past the last, its RMS level
    from 0 to 1), from the frames louder than SPEECH_DB. None: no speech at all."""
    frame = max(1, int(FRAME_SECONDS * sample_rate))
    count = samples.size // frame
    if not count:
        return None
    frames = samples[: count * frame].astype(np.float64).reshape(count, frame) / 32768.0
    energy = np.mean(frames ** 2, axis=1)
    active = energy > 10 ** (SPEECH_DB / 10)
    if not active.any():
        return None
    first, last = int(np.argmax(active)), count - 1 - int(np.argmax(active[::-1]))
    return first * frame, (last + 1) * frame, float(np.sqrt(np.mean(energy[active])))


def _flat_peaks(samples: np.ndarray) -> int:
    """How many times the voice sits at full scale for CLIP_RUN samples or more."""
    clipped = np.abs(samples.astype(np.int32)) >= CLIP_LEVEL
    if not clipped.any():
        return 0
    edges = np.flatnonzero(np.diff(np.concatenate(([0], clipped.astype(np.int8), [0]))))
    return int(np.sum(edges[1::2] - edges[::2] >= CLIP_RUN))


def _voice_samples(path: Path, sample_rate: int) -> np.ndarray:
    """A voice's 16-bit mono samples: read straight from the WAV the engine wrote, or decoded
    by FFmpeg when it is any other kind of file."""
    samples = media.read_pcm16_wav(path, sample_rate, 1)
    if samples is None:
        samples = media.decode_pcm16(path, sample_rate, 1)
    return samples[:, 0]


def measure_voice(samples: np.ndarray, sample_rate: int) -> dict:
    """Objective measurements of one voice (16-bit mono samples): its loudest sample, the level
    of its speech, the silence before and after it, its clipped peaks. Values in dBFS (0 is
    full scale) and seconds."""
    total = samples.size / sample_rate
    peak = float(np.max(np.abs(samples.astype(np.int32)))) / 32768.0 if samples.size else 0.0
    speech = _speech(samples, sample_rate)
    if speech is None:
        lead, trail, level = total, 0.0, None
    else:
        lead, trail = speech[0] / sample_rate, (samples.size - speech[1]) / sample_rate
        level = _db(speech[2])
    return {"crete_db": _db(peak), "niveau_db": level, "silence_debut_s": round(lead, 2),
            "silence_fin_s": round(trail, 2), "ecretages": _flat_peaks(samples)}


def trim_silence(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """The voice without the silence before and after its speech (TRIM_MARGIN kept on each
    side). Never touches a pause inside the speech; a voice with no speech is left as it is."""
    speech = _speech(samples, sample_rate)
    if speech is None:
        return samples
    margin = int(TRIM_MARGIN * sample_rate)
    return samples[max(0, speech[0] - margin): min(samples.size, speech[1] + margin)]


class VoiceTimingError(RuntimeError):
    """A voice cannot go into the final film: it does not fit in its pause, runs into the next
    voice, or cannot be heard. The final export stops before anything is mixed. `problems`
    lists them; `placed` has every measured voice."""

    def __init__(self, problems: list[dict], placed: list[dict]):
        super().__init__("\n".join(p["message"] for p in problems))
        self.problems, self.placed = problems, placed


def _problem(voice: dict, code: str, severity: str, value, unit: str, threshold: str,
             action: str, message: str, **extra) -> dict:
    """One finding, as the transparency report lists it."""
    return {"id": voice["id"], "debut_s": voice.get("debut_s"), "code": code,
            "gravite": severity, "mesure": value, "unite": unit, "seuil": threshold,
            "action": action, "message": message, **extra}


def _edge_silence(voice: dict) -> str:
    """For a voice too long for its pause: the silence it carries before and after its speech,
    when there is enough of it to matter."""
    lead, trail = voice.get("silence_debut_s", 0.0), voice.get("silence_fin_s", 0.0)
    if lead + trail < 0.2:
        return ""
    if lead >= 0.1 and trail >= 0.1:
        where = f"contient {_s(lead)} s de silence au début et {_s(trail)} s à la fin"
    elif lead >= 0.1:
        where = f"commence par {_s(lead)} s de silence"
    else:
        where = f"finit par {_s(trail)} s de silence"
    return f" Elle {where} : « --couper-silences » retire ce silence."


def timing_problems(placed: list[dict]) -> list[dict]:
    """Each voice must end inside its own pause (so before the dialogue comes back) and before
    the next voice starts. Fills in « chevauche » on the voices that run into the next one."""
    problems = []
    ordered = sorted(placed, key=lambda p: p["debut_s"])
    for i, voice in enumerate(ordered):
        if voice["deborde"]:
            into = ("sur le dialogue" if voice["fin_voix_s"] > voice["fin_pause_s"]
                    else "dans la marge avant le dialogue")
            accel = f", accélérée ×{voice['acceleration']:.2f}".replace(".", ",") \
                if voice["acceleration"] > 1.0 else ""
            silence = "" if voice.get("silence_coupe_s") else _edge_silence(voice)
            problems.append(_problem(
                voice, "deborde", BLOCKING, voice["depassement_s"], "s",
                "la voix finit dans sa pause",
                "Raccourcissez ce passage dans l'éditeur.",
                f"{voice['id']} : {_s(voice['duree_voix_s'])} s de voix{accel} pour "
                f"{_s(voice['duree_disponible_s'])} s disponibles ; elle déborde de "
                f"{_s(voice['depassement_s'])} s {into}.{silence}"))
        following = ordered[i + 1] if i + 1 < len(ordered) else None
        if following and voice["fin_voix_s"] > following["debut_s"]:
            voice["chevauche"] = following["id"]
            problems.append(_problem(
                voice, "chevauche", BLOCKING,
                round(voice["fin_voix_s"] - following["debut_s"], 2), "s",
                "la voix finit avant la suivante", "Raccourcissez ce passage dans l'éditeur.",
                f"{voice['id']} : sa voix chevauche celle de {following['id']}.",
                avec=following["id"]))
    return problems


def quality_problems(placed: list[dict]) -> list[dict]:
    """What the measurements say about each voice. A voice that cannot be heard blocks a final
    export (its passage would be lost to the viewer); clipping, a level far from the other
    voices, speech much shorter than its text and long silences are warnings. Nothing is ever
    corrected here: each finding says what was measured, against what, and what to do."""
    problems = []
    heard = [v for v in placed if v.get("crete_db") is not None
             and v["crete_db"] >= SILENT_PEAK_DB and v.get("niveau_db") is not None]
    median = float(np.median([v["niveau_db"] for v in heard])) if len(heard) >= 2 else None
    for voice in placed:
        if voice.get("crete_db") is None:          # not measured
            continue
        vid = voice["id"]
        if voice["crete_db"] < SILENT_PEAK_DB:
            problems.append(_problem(
                voice, "muette", BLOCKING, voice["crete_db"], "dBFS",
                f"crête au-dessus de {SILENT_PEAK_DB:.0f} dBFS",
                "Écoutez le fichier (micro coupé ?) et refaites cette voix.",
                f"{vid} : voix muette ou presque (crête à {_s(voice['crete_db'])} dBFS) : "
                "ce passage ne serait pas entendu."))
            continue
        if voice.get("ecretages", 0) >= CLIP_ALERT:
            problems.append(_problem(
                voice, "ecretage", WARNING, voice["ecretages"], "crêtes écrêtées",
                f"moins de {CLIP_ALERT}", "Réenregistrez moins fort ou plus loin du micro.",
                f"{vid} : son saturé ({voice['ecretages']} crêtes écrêtées), la voix peut "
                "grésiller."))
        if median is not None and voice.get("niveau_db") is not None:
            gap = round(voice["niveau_db"] - median, 1)
            if abs(gap) > LEVEL_GAP_DB:
                problems.append(_problem(
                    voice, "volume", WARNING, voice["niveau_db"], "dBFS",
                    f"à ±{LEVEL_GAP_DB:.0f} dB de la médiane des voix ({_s(median)} dBFS)",
                    "Refaites cette voix au même volume que les autres.",
                    f"{vid} : voix {'plus forte' if gap > 0 else 'plus faible'} que les autres "
                    f"de {_s(abs(gap))} dB ({_s(voice['niveau_db'])} dBFS, médiane "
                    f"{_s(median)} dBFS).", ecart_db=gap))
        needed = voice.get("duree_texte_s") or 0.0
        speech = voice.get("duree_parole_s")
        if needed >= SHORT_MIN_TEXT and speech is not None and speech < SHORT_RATIO * needed:
            problems.append(_problem(
                voice, "trop_courte", WARNING, speech, "s",
                f"au moins {round(100 * SHORT_RATIO)} % des {_s(needed)} s que demande le texte",
                "Vérifiez que le fichier est bien celui de ce passage, et qu'il n'est pas coupé.",
                f"{vid} : {_s(speech)} s de parole pour un texte qui en demande environ "
                f"{_s(needed)} : mauvais fichier, ou enregistrement coupé ?"))
        if not voice.get("silence_coupe_s"):
            for side, where in (("debut", "au début"), ("fin", "à la fin")):
                quiet = voice.get(f"silence_{side}_s", 0.0)
                if quiet > EDGE_SILENCE:
                    problems.append(_problem(
                        voice, f"silence_{side}", WARNING, quiet, "s",
                        f"{_s(EDGE_SILENCE)} s au plus",
                        "Relancez avec « --couper-silences », ou refaites la voix en parlant "
                        "tout de suite.",
                        f"{vid} : {_s(quiet)} s de silence {where} de la voix"
                        + (" : la description commence en retard." if side == "debut"
                           else " : le son du film reste baissé pour rien.")))
    return problems


def _envelope(start: int, end: int, n: int, depth: float, ramp: int) -> tuple[int, np.ndarray | None]:
    """The gain that ducks the film under one voice: (first sample, values), None if empty."""
    a, b = max(0, start - ramp), min(n, end + ramp)
    if b <= a:
        return a, None
    env = np.full(b - a, depth, dtype=np.float32)
    down, up = start - a, b - end
    if down > 0:
        env[:down] = np.linspace(1.0, depth, down, endpoint=False)
    if up > 0:
        env[-up:] = np.linspace(depth, 1.0, up)
    return a, env


def duck(gain: np.ndarray, start: int, end: int, depth: float, ramp: int) -> None:
    """Lower gain to `depth` between start and end, with smooth ramps on both sides."""
    a, env = _envelope(start, end, gain.size, depth, ramp)
    if env is not None:
        gain[a:a + env.size] = np.minimum(gain[a:a + env.size], env)


@dataclass
class _Voice:
    start: int        # first sample in the film
    end: int          # one past the last sample, never beyond the film
    pcm: Path         # its samples, 16-bit mono, already cut at the end of the film


def _slice(lo: int, hi: int, film_pcm: Path | None, voices: list[_Voice], n: int,
           depth: float, ramp: int) -> tuple[np.ndarray, np.ndarray]:
    """Mix samples [lo, hi) exactly as the whole-film mix would: (stereo mix, voice alone)."""
    m = hi - lo
    if film_pcm is None:
        base = np.zeros((m, 2), dtype=np.float32)
    else:
        pcm = np.fromfile(film_pcm, dtype="<i2", count=2 * m, offset=4 * lo)
        base = (pcm.astype(np.float32) / 32768.0).reshape(-1, 2)
    gain = np.ones(m, dtype=np.float32)
    voice = np.zeros(m, dtype=np.float32)
    for v in voices:   # in the order they were placed, as in the whole-film mix
        if v.start < hi + ramp and v.end + ramp > lo:
            a, env = _envelope(v.start, v.end, n, depth, ramp)
            if env is not None and a < hi and a + env.size > lo:
                s, e = max(lo, a), min(hi, a + env.size)
                gain[s - lo:e - lo] = np.minimum(gain[s - lo:e - lo], env[s - a:e - a])
        if v.start < hi and v.end > lo:
            s, e = max(lo, v.start), min(hi, v.end)
            samples = np.fromfile(v.pcm, dtype="<i2", count=e - s, offset=2 * (s - v.start))
            voice[s - lo:e - lo] += samples.astype(np.float32) / 32768.0
    mixed = base * gain[:, None] + 0.9 * voice[:, None]
    return mixed, voice


def build_mix(video: Path, segments: list, out_dir: Path, *, langue: str, moteur: str,
              voix: str | None, enregistrements: Path | None, duree: float,
              attenuation_db: float = -12.0, tempo_max: float = 1.3, sample_rate: int = 48000,
              log: Callable[[str], None] = print,
              chunk_seconds: float = MIX_CHUNK_SECONDS, strict: bool = False,
              couper_silences: bool = False, mots_par_seconde: float | None = None) -> dict:
    """Voice every passage, measure each voice, then mix. strict (the final export): a voice
    that does not fit in its pause, runs into the next voice or cannot be heard raises
    VoiceTimingError before any mixing; a working version (not strict) is mixed anyway and the
    problems are listed. Warnings never stop anything. couper_silences: remove the silence
    before and after each voice (asked for explicitly; the speech itself is never touched)."""
    voices_dir = out_dir / "voix"
    voices_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".mixage-", dir=out_dir))   # removed at the end
    try:
        if media.has_audio(video):
            film_pcm = work / "film.s16"
            n = media.decode_audio_to_file(video, film_pcm, sample_rate, 2)
        else:
            film_pcm, n = None, int(round(duree * sample_rate))
        depth, ramp = 10 ** (attenuation_db / 20), int(0.15 * sample_rate)
        placed, voices, lost = [], [], []

        for seg in segments:
            raw = voices_dir / f"{seg.id}.source.wav"
            synthesize(moteur, seg.texte, raw, langue=langue, voix=voix, segment_id=seg.id,
                       enregistrements=enregistrements, sample_rate=sample_rate)
            source = _voice_samples(raw, sample_rate)
            measured = measure_voice(source, sample_rate)   # the voice as made, before any change
            measured["duree_parole_s"] = round(max(0.0, source.size / sample_rate
                                                   - measured["silence_debut_s"]
                                                   - measured["silence_fin_s"]), 2)
            measured["duree_texte_s"] = round(estimated_seconds(seg.texte, langue,
                                                                mots_par_seconde), 2)
            if couper_silences:
                kept_part = trim_silence(source, sample_rate)
                if kept_part.size < source.size:
                    media.write_wav(raw, kept_part.astype(np.float32) / 32768.0, sample_rate)
                    measured["silence_coupe_s"] = round((source.size - kept_part.size)
                                                        / sample_rate, 2)
                    source = _voice_samples(raw, sample_rate)    # exactly what the file holds
            spoken = media.duration(raw)
            available = max(0.3, seg.duree_parole)
            tempo = min(tempo_max, spoken / available) if spoken > available else 1.0
            fitted = voices_dir / f"{seg.id}.wav"
            if tempo > 1.0:  # speed up slightly rather than talk over the actors
                media.to_wav(raw, fitted, sample_rate, 1, tempo)
                raw.unlink(missing_ok=True)
                pcm = media.decode_pcm16(fitted, sample_rate, 1)[:, 0]
            else:            # the same file, renamed: its samples are already read
                os.replace(raw, fitted)
                pcm = source
            start = int(round(seg.parole_debut * sample_rate))
            film_end = n / sample_rate
            if start >= n:   # never dropped in silence: a final export stops on it
                lost.append(_problem(
                    {"id": seg.id, "debut_s": seg.parole_debut}, "hors_film", BLOCKING,
                    round(seg.parole_debut, 2), "s", f"avant la fin du film ({_s(film_end)} s)",
                    "Vérifiez que la vidéo est bien celle de la préparation.",
                    f"{seg.id} : commence à {_s(seg.parole_debut)} s, après la fin du film "
                    f"({_s(film_end)} s) : ce passage serait perdu."))
                continue
            end = min(n, start + pcm.size)
            kept = work / f"{seg.id}.s16"
            pcm[: end - start].tofile(kept)
            voices.append(_Voice(start, end, kept))
            length = pcm.size / sample_rate
            overflow = round(max(0.0, length - available), 2)
            cut = round((start + pcm.size - end) / sample_rate, 2)
            if cut > OVERRUN_TOLERANCE and overflow <= OVERRUN_TOLERANCE:
                lost.append(_problem(
                    {"id": seg.id, "debut_s": seg.parole_debut}, "coupee", BLOCKING, cut, "s",
                    "la voix finit avant la fin du film",
                    "Vérifiez que la vidéo est bien celle de la préparation.",
                    f"{seg.id} : la fin du film couperait {_s(cut)} s de cette voix."))
            if overflow > OVERRUN_TOLERANCE:
                log(f"  {seg.id} : la voix dépasse la pause de {overflow:.2f} s, texte à raccourcir.")
            placed.append({"id": seg.id, "debut_s": seg.parole_debut, "duree_voix_s": round(length, 2),
                           "duree_disponible_s": round(available, 2), "acceleration": round(tempo, 2),
                           "depassement_s": overflow, "duree_source_s": round(spoken, 2),
                           "fin_voix_s": round(seg.parole_debut + length, 3),
                           "limite_s": round(seg.parole_debut + available, 3),
                           "fin_pause_s": round(seg.fin, 3),
                           "deborde": overflow > OVERRUN_TOLERANCE, "chevauche": "",
                           **measured})

        problems = timing_problems(placed)
        checks = quality_problems(placed) + lost
        for voice in placed:
            voice["alertes"] = [c["code"] for c in problems + checks if c["id"] == voice["id"]]
        blocking = problems + [c for c in checks if c["gravite"] == BLOCKING]
        if blocking and strict:
            raise VoiceTimingError(blocking, placed)
        for problem in problems:
            if problem["code"] == "chevauche":
                log(f"  {problem['message']}")
        for check in checks:
            log(f"  {'Bloquant' if check['gravite'] == BLOCKING else 'Alerte'} : "
                f"{check['message']}")

        step = max(1, round(chunk_seconds * sample_rate))
        slices = [(lo, min(n, lo + step)) for lo in range(0, n, step)]
        mixed_path, voice_path = out_dir / "piste_audiodecrite.wav", out_dir / "voix_seule.wav"
        peak = 0.0
        # First pass: write both files and measure the loudest sample of the whole mix.
        with media.WavWriter(mixed_path, 2, sample_rate) as mixed_out, \
                media.WavWriter(voice_path, 1, sample_rate) as voice_out:
            for lo, hi in slices:
                mixed, voice = _slice(lo, hi, film_pcm, voices, n, depth, ramp)
                if mixed.size:
                    peak = max(peak, float(np.max(np.abs(mixed))))
                mixed_out.write(mixed)
                voice_out.write(voice)
        if peak > PEAK_LIMIT:   # too loud somewhere: the same gain for the whole film
            scale = PEAK_LIMIT / peak
            with media.WavWriter(mixed_path, 2, sample_rate) as mixed_out:
                for lo, hi in slices:
                    mixed, _ = _slice(lo, hi, film_pcm, voices, n, depth, ramp)
                    mixed *= scale
                    mixed_out.write(mixed)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"piste_mixee": mixed_path, "voix_seule": voice_path, "passages": placed,
            "problemes": problems, "controles": checks}

"""E03 · The mix is computed a slice at a time; the result must not change by a single sample,
and the memory it needs must not grow with the length of the film."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from wasf import media
from wasf.mix import build_mix
from wasf.project import Segment

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg n'est pas installé")

RATE = 48000


def _film(path: Path, seconds: float, *, audio: str | None = "normal") -> Path:
    """A tiny grey film; audio: None (no sound track), « normal », or « fort » (near full scale,
    so the mix has to be turned down)."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
           "-i", f"color=c=gray:s=64x36:r=5:d={seconds}"]
    if audio:
        level = 0.97 if audio == "fort" else 0.3
        cmd += ["-f", "lavfi", "-i",
                f"aevalsrc='{level}*sin(2*PI*330*t)|{level}*sin(2*PI*331*t)':s={RATE}:d={seconds}"]
    cmd += ["-map", "0:v"] + (["-map", "1:a", "-c:a", "aac", "-b:a", "128k"] if audio else [])
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def _segments() -> list[Segment]:
    """Voices that cross slice limits, two that overlap, one sped up, one cut by the end of the
    film and one that starts after it."""
    def seg(i, start, stop, text):
        return Segment(id=f"p{i:03d}", debut=start - 0.3, fin=stop + 0.3, parole_debut=start,
                       parole_fin=stop, budget_mots=30, texte=text)
    return [seg(1, 0.4, 3.0, "Un plan fixe sur la ville au matin."),
            seg(2, 3.3, 4.6, "Une porte s'ouvre lentement sur une cour vide et silencieuse."),
            seg(3, 4.2, 6.0, "Deux voix se croisent ici."),
            seg(4, 7.1, 9.9, "La lumière baisse."),
            seg(5, 11.2, 13.0, "Le dernier plan dure encore un peu."),
            seg(6, 13.5, 13.9, "Coupée par la fin."),
            seg(7, 14.5, 15.0, "Après la fin.")]


def _old_decode(path: Path, channels: int) -> np.ndarray:
    """Decoding as Wasf 0.1.0 did it, kept here so the reference does not depend on the code
    under test."""
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", str(channels),
                           "-ar", str(RATE), "-f", "s16le", "-"], capture_output=True, check=True)
    return (np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0).reshape(-1, channels)


def _old_duck(gain, start, end, depth, ramp):
    n = gain.size
    a, b = max(0, start - ramp), min(n, end + ramp)
    if b <= a:
        return
    env = np.full(b - a, depth, dtype=np.float32)
    down, up = start - a, b - end
    if down > 0:
        env[:down] = np.linspace(1.0, depth, down, endpoint=False)
    if up > 0:
        env[-up:] = np.linspace(depth, 1.0, up)
    gain[a:b] = np.minimum(gain[a:b], env)


def _reference(film: Path, voices_dir: Path, segments, duree: float, attenuation_db: float):
    """The whole-film mix of Wasf 0.1.0, from the same voice files: (mix, voice alone)."""
    if media.has_audio(film):
        base = _old_decode(film, 2)
    else:
        base = np.zeros((round(duree * RATE), 2), dtype=np.float32)
    n = base.shape[0]
    gain, voice = np.ones(n, dtype=np.float32), np.zeros(n, dtype=np.float32)
    depth, ramp = 10 ** (attenuation_db / 20), int(0.15 * RATE)
    for seg in segments:
        samples = _old_decode(voices_dir / f"{seg.id}.wav", 1)[:, 0]
        start = round(seg.parole_debut * RATE)
        if start >= n:
            continue
        end = min(n, start + samples.size)
        voice[start:end] += samples[: end - start]
        _old_duck(gain, start, end, depth, ramp)
    mixed = base * gain[:, None] + 0.9 * voice[:, None]
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    if peak > 0.98:
        mixed *= 0.98 / peak
    return mixed, voice


@pytest.mark.parametrize("audio,chunk,attenuation", [
    ("normal", 1.7, -12.0),      # slices end inside voices and inside ramps
    ("normal", 0.05, -12.0),     # very small slices
    ("normal", 30.0, -12.0),     # the default: the whole clip in one slice
    ("fort", 1.7, 0.0),          # loud film, no ducking: the whole mix is turned down
    (None, 1.7, -12.0),          # a film without a sound track
])
def test_chunked_mix_is_identical_to_whole_film_mix(tmp_path, audio, chunk, attenuation):
    film = _film(tmp_path / "film.mp4", 14.0, audio=audio)
    segments = _segments()
    out = tmp_path / "export"
    result = build_mix(film, segments, out, langue="fr", moteur="bip", voix=None,
                       enregistrements=None, duree=14.0, attenuation_db=attenuation,
                       log=lambda _m: None, chunk_seconds=chunk)
    mixed, voice = _reference(film, out / "voix", segments, 14.0, attenuation)
    if audio == "fort":
        assert float(np.max(np.abs(mixed))) > 0.97   # the turned-down path was really taken
    reference_mix = media.write_wav(tmp_path / "reference_mix.wav", mixed)
    reference_voice = media.write_wav(tmp_path / "reference_voix.wav", voice)
    assert result["piste_mixee"].read_bytes() == reference_mix.read_bytes()
    assert result["voix_seule"].read_bytes() == reference_voice.read_bytes()
    assert [p["id"] for p in result["passages"]] == ["p001", "p002", "p003", "p004", "p005", "p006"]
    assert not [p for p in out.iterdir() if p.name.startswith(".mixage-")]   # nothing left behind


MEASURE = (
    "import json, resource, sys\n"
    "from pathlib import Path\n"
    "from wasf.mix import build_mix\n"
    "from wasf.project import Segment\n"
    "film, out, minutes = Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3])\n"
    "segs = [Segment(id=f'p{i}', debut=t, fin=t + 4, parole_debut=t + 0.3, parole_fin=t + 3.7,\n"
    "                budget_mots=8, texte='Un plan fixe sur la ville.')\n"
    "        for i, t in enumerate([10.0, 60.0, 100.0])]\n"
    "build_mix(film, segs, out, langue='fr', moteur='bip', voix=None, enregistrements=None,\n"
    "          duree=minutes * 60, log=lambda s: None)\n"
    "print(json.dumps({'peak_mb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}))\n")


@pytest.mark.skipif(sys.platform == "win32", reason="resource n'existe pas sous Windows")
def test_mix_memory_does_not_grow_with_the_film(tmp_path):
    peaks = {}
    for minutes in (2, 8):
        film = _film(tmp_path / f"film_{minutes}.mp4", minutes * 60)
        run = subprocess.run([sys.executable, "-c", MEASURE, str(film), str(tmp_path / f"out_{minutes}"),
                              str(minutes)], capture_output=True, text=True, check=True)
        peaks[minutes] = json.loads(run.stdout.strip().splitlines()[-1])["peak_mb"]
    # Mixing the whole film at once needed about 93 MB more per minute of film.
    assert peaks[8] - peaks[2] < 40, peaks

"""Thin wrappers around FFmpeg / ffprobe, plus WAV helpers (numpy only)."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np


class MediaError(RuntimeError):
    """FFmpeg is missing or a media command failed."""


def require_ffmpeg() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise MediaError(
            "FFmpeg est introuvable (" + ", ".join(missing) + "). "
            "Installez-le depuis https://ffmpeg.org puis ajoutez-le au PATH."
        )


def run(cmd: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd, input=input_text, capture_output=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise MediaError(f"Échec de la commande : {' '.join(cmd)}\n{proc.stderr[-1500:]}")
    return proc


def probe(path: Path) -> dict:
    proc = run(["ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(path)])
    return json.loads(proc.stdout or "{}")


def audio_problem(path: Path) -> str:
    """Why this file cannot be used as a voice, or '' when it holds sound FFmpeg can read."""
    try:
        info = probe(path)
    except (MediaError, ValueError):     # FFmpeg refused it, or answered no JSON
        return "illisible"
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        return "aucun son dedans"
    try:
        seconds = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):   # no length given: let FFmpeg try when the voice is made
        return ""
    return "vide" if seconds < 0.05 else ""


def duration(path: Path) -> float:
    info = probe(path)
    value = info.get("format", {}).get("duration")
    if value is not None:
        return float(value)
    durations = [float(s["duration"]) for s in info.get("streams", []) if s.get("duration")]
    if not durations:
        raise MediaError(f"Durée introuvable pour {path}")
    return max(durations)


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))


def video_size(path: Path) -> tuple[int, int, float]:
    """Return (width, height, fps) of the first video stream."""
    for stream in probe(path).get("streams", []):
        if stream.get("codec_type") == "video":
            num, _, den = (stream.get("avg_frame_rate") or "25/1").partition("/")
            try:
                fps = float(num) / float(den or 1)
            except (ValueError, ZeroDivisionError):
                fps = 25.0
            return int(stream["width"]), int(stream["height"]), fps or 25.0
    raise MediaError(f"Aucune piste vidéo dans {path}")


FINGERPRINT_SLICE = 1 << 20   # 1 MiB read at the start, the middle and the end of the file


def fingerprint(path: Path) -> str:
    """A quick identity for a video file: its size and a SHA-256 of three 1 MiB slices (start,
    middle, end). Instant even for a feature film, and any new edit or re-encode changes it.
    It says the file changed, not how: a re-encode of the same edit changes it too."""
    path = Path(path)
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode())
    with path.open("rb") as handle:
        for start in (0, max(0, size // 2 - FINGERPRINT_SLICE // 2),
                      max(0, size - FINGERPRINT_SLICE)):
            handle.seek(start)
            digest.update(handle.read(FINGERPRINT_SLICE))
    return f"{size}:{digest.hexdigest()[:32]}"


def extract_frame(video: Path, t: float, out_jpg: Path, max_width: int = 768) -> Path:
    """Save one JPEG frame at time t, at most max_width pixels wide (fewer tokens, less energy)."""
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale='min({max_width},iw)':-2", "-q:v", "4", str(out_jpg)])
    if not out_jpg.exists():
        raise MediaError(f"Aucune image extraite à {t:.2f} s de {video}")
    return out_jpg


THUMB_SIZE = (64, 36)   # tiny grey frames, only to see where the image changes
STILL = 6.0             # under this change score, a stretch counts as a still shot
TOP_SHARE = 0.10        # the score is the mean of the 10 % most changed pixels


def _overlap_change(a: np.ndarray, b: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """|a - b| where they overlap once b is read (dy, dx) pixels further on."""
    h, w = a.shape
    da = a[max(0, -dy):min(h, h - dy), max(0, -dx):min(w, w - dx)]
    db = b[max(0, dy):min(h, h + dy), max(0, dx):min(w, w + dx)]
    return np.abs(da - db)


def change_score(a: np.ndarray, b: np.ndarray, align: bool = True) -> float:
    """How differently two tiny frames look, so that a gesture counts and the camera does not:
    a pan between them is undone first (phase correlation), a fade or a light change is
    taken out by comparing each frame to its own average, and only the most changed pixels
    are counted, so a small hand outweighs a slow drift of the whole image."""
    width, height = THUMB_SIZE
    a = a.astype(np.float32).reshape(height, width)
    b = b.astype(np.float32).reshape(height, width)
    a, b = a - a.mean(), b - b.mean()
    shifts = [(0, 0)]
    if align:
        window = np.outer(np.hanning(height), np.hanning(width))
        cross = np.fft.fft2(a * window) * np.conj(np.fft.fft2(b * window))
        peak = np.unravel_index(int(np.argmax(np.abs(np.fft.ifft2(cross / (np.abs(cross)
                                                                             + 1e-9))))),
                                (height, width))
        dy, dx = (p if p <= n // 2 else p - n for p, n in zip(peak, (height, width)))
        if abs(dy) <= height // 3 and abs(dx) <= width // 3:   # farther: a cut, not a pan
            shifts += [(dy, dx), (-dy, -dx)]
    scores = []
    for dy, dx in shifts:
        change = np.sort(_overlap_change(a, b, dy, dx).ravel())
        scores.append(float(change[-max(1, int(len(change) * TOP_SHARE)):].mean()))
    return min(scores)


def thumbnails(video: Path, start: float, length: float, count: int,
               fps: float | None = None) -> list[tuple[float, np.ndarray]]:
    """`count` tiny grey frames spread evenly over [start, start + length), as (time, pixels).
    One FFmpeg call decodes the stretch; the times come from the frame rate, so each picked
    frame is the one later extracted at full size. Fewer, or none, past the end of the video."""
    if count <= 0 or length <= 0:
        return []
    rate = fps or video_size(video)[2] or 25.0
    width, height = THUMB_SIZE
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-i", str(video),
         "-t", f"{length:.3f}", "-vf", f"scale={width}:{height},format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise MediaError(f"Vignettes impossibles à {start:.2f} s de {video}")
    size = width * height
    data = np.frombuffer(proc.stdout, dtype=np.uint8)
    decoded = len(data) // size
    if not decoded:
        return []
    picks = sorted({min(decoded - 1, int((k + 0.5) * decoded / count)) for k in range(count)})
    return [(round(max(0.0, start) + i / rate, 3), data[i * size:(i + 1) * size]) for i in picks]


def most_distinct(frames: list[tuple[float, np.ndarray]], count: int,
                  align: bool = True) -> list[float] | None:
    """The `count` times whose frames differ most from one another (change_score), in film
    order: the moments where something changes. None for a still shot or too few frames."""
    if count <= 0 or len(frames) < count + 1:
        return None
    n = len(frames)
    gap = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            gap[i, j] = gap[j, i] = change_score(frames[i][1], frames[j][1], align)
    if gap.max() < STILL:
        return None
    first, second = np.unravel_index(int(np.argmax(gap)), gap.shape)
    chosen = sorted({int(first), int(second)})[:count]
    while len(chosen) < count:      # then the frame farthest from everything chosen so far
        rest = [i for i in range(n) if i not in chosen]
        chosen.append(max(rest, key=lambda i: (min(gap[i, j] for j in chosen), -i)))
    return [round(frames[i][0], 3) for i in sorted(chosen)]


def _decode_command(path: Path, sample_rate: int, channels: int, target: str) -> list[str]:
    return ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", str(channels),
            "-ar", str(sample_rate), "-f", "s16le", target]


def decode_pcm16(path: Path, sample_rate: int = 48000, channels: int = 2) -> np.ndarray:
    """Decode any audio/video file to 16-bit samples shaped (n, channels)."""
    proc = subprocess.run(_decode_command(path, sample_rate, channels, "-"), capture_output=True,
                          check=False)
    if proc.returncode != 0:
        raise MediaError(f"Décodage audio impossible : {path}\n"
                         f"{proc.stderr.decode('utf-8', 'replace')[-800:]}")
    return np.frombuffer(proc.stdout, dtype="<i2").reshape(-1, channels)


def read_pcm16_wav(path: Path, sample_rate: int, channels: int) -> np.ndarray | None:
    """The samples of a plain 16-bit PCM WAV at this rate and channel count, read directly,
    without starting FFmpeg (shaped (n, channels)). None for any other kind of file: decode
    those with decode_pcm16."""
    try:
        with wave.open(str(path), "rb") as wav:
            if (wav.getsampwidth(), wav.getframerate(), wav.getnchannels(),
                    wav.getcomptype()) != (2, sample_rate, channels, "NONE"):
                return None
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError, OSError):
        return None
    return np.frombuffer(frames, dtype="<i2").reshape(-1, channels)


def decode_audio(path: Path, sample_rate: int = 48000, channels: int = 2) -> np.ndarray:
    """Decode any audio/video file to float32 samples shaped (n, channels)."""
    return decode_pcm16(path, sample_rate, channels).astype(np.float32) / 32768.0


def decode_audio_to_file(path: Path, out_pcm: Path, sample_rate: int = 48000,
                         channels: int = 2) -> int:
    """Decode a file's sound to raw 16-bit samples on disk, without holding them in memory
    (the same samples as decode_pcm16). Returns the number of frames."""
    out_pcm = Path(out_pcm)
    out_pcm.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(_decode_command(path, sample_rate, channels, str(out_pcm)),
                          capture_output=True, check=False)
    if proc.returncode != 0:
        raise MediaError(f"Décodage audio impossible : {path}\n"
                         f"{proc.stderr.decode('utf-8', 'replace')[-800:]}")
    return out_pcm.stat().st_size // (2 * channels)


def _pcm16(samples: np.ndarray) -> bytes:
    if samples.ndim == 1:
        samples = samples[:, None]
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = 48000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(samples.shape[1] if samples.ndim > 1 else 1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(_pcm16(samples))
    return path


class WavWriter:
    """A 16-bit WAV written a slice at a time: the same bytes as write_wav() on the whole
    signal, without holding it in memory."""

    def __init__(self, path: Path, channels: int, sample_rate: int = 48000):
        self.path, self.channels, self.sample_rate = Path(path), channels, sample_rate
        self._wav = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._wav = wave.open(str(self.path), "wb")
        self._wav.setnchannels(self.channels)
        self._wav.setsampwidth(2)
        self._wav.setframerate(self.sample_rate)
        return self

    def write(self, samples: np.ndarray) -> None:
        self._wav.writeframes(_pcm16(samples))

    def __exit__(self, *exc) -> bool:
        self._wav.close()
        return False


def to_wav(src: Path, dst: Path, sample_rate: int = 48000, channels: int = 1,
           tempo: float = 1.0) -> Path:
    """Convert any audio file to PCM WAV, optionally speeding it up (atempo)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    if abs(tempo - 1.0) > 1e-3:
        cmd += ["-af", f"atempo={tempo:.4f}"]
    cmd += ["-ac", str(channels), "-ar", str(sample_rate), str(dst)]
    run(cmd)
    return dst


def mux(video: Path, mixed_wav: Path, out_mp4: Path, lang3: str = "fra",
        keep_original: bool = True) -> Path:
    """Video + described mix as the default track (+ original sound as a second track)."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    original = keep_original and has_audio(video)
    base = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(mixed_wav),
            "-map", "0:v:0", "-map", "1:a:0"]
    if original:
        base += ["-map", "0:a:0"]
    meta = ["-metadata:s:a:0", "title=Audiodescription", "-metadata:s:a:0", f"language={lang3}",
            "-disposition:a:0", "default"]
    if original:
        meta += ["-metadata:s:a:1", "title=Version originale", "-disposition:a:1", "0"]
    tail = ["-c:a", "aac", "-b:a", "192k"] + meta + ["-movflags", "+faststart", str(out_mp4)]
    try:
        run(base + ["-c:v", "copy"] + tail)
    except MediaError:  # source codec not allowed in MP4: re-encode the picture
        run(base + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p"] + tail)
    return out_mp4


def prepend_card(film_mp4: Path, announce_wav: Path, out_mp4: Path, seconds: float,
                 card_png: Path | None = None) -> Path:
    """Put a short title card with the spoken AI disclosure before the film."""
    width, height, fps = video_size(film_mp4)
    fps_txt = f"{fps:.3f}"
    if card_png is not None and card_png.exists():
        card_input = ["-loop", "1", "-t", f"{seconds:.2f}", "-i", str(card_png)]
    else:
        card_input = ["-f", "lavfi", "-t", f"{seconds:.2f}",
                      "-i", f"color=c=black:s={width}x{height}:r={fps_txt}"]
    graph = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps_txt},"
        f"format=yuv420p[v0];"
        f"[1:a]apad,atrim=0:{seconds:.2f},aformat=sample_rates=48000:channel_layouts=stereo[a0];"
        f"[2:v:0]setsar=1,fps={fps_txt},format=yuv420p[v1];"
        f"[2:a:0]aformat=sample_rates=48000:channel_layouts=stereo[a1];"
        f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )
    run(["ffmpeg", "-y", "-loglevel", "error", *card_input, "-i", str(announce_wav),
         "-i", str(film_mp4), "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
         "-metadata:s:a:0", "title=Audiodescription", "-movflags", "+faststart", str(out_mp4)])
    return out_mp4

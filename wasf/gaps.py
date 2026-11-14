"""Find the pauses in the dialogue where a description can be spoken.

Two sources, in order of reliability:
1. the subtitle file (SRT or WebVTT): pauses = time between two lines;
2. the soundtrack: pauses = silences found by FFmpeg (less reliable under music).
"""
from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import media
from .timecode import parse_tc


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class Window:
    start: float
    end: float
    source: str  # "sous-titres" | "silence"

    @property
    def duration(self) -> float:
        return self.end - self.start


_TAGS = re.compile(r"<[^>]+>|\{[^}]+\}")


class SubtitleError(ValueError):
    """The subtitle file cannot be read as text: its encoding is not one Wasf recognises."""


ENCODING_NAMES = {"utf-8": "UTF-8", "utf-16": "UTF-16", "cp1256": "Windows-1256 (arabe)",
                  "iso8859_6": "ISO-8859-6 (arabe)", "cp1252": "Windows-1252 (latin)"}

_ARABIC_LETTER = re.compile(r"[ؠ-يٮ-ۓۺ-ۿݐ-ݿ]")
_ASCII_LETTER = re.compile(r"[A-Za-z]")
_ACCENTED_ONLY = re.compile(r"^[À-ÿ]{3,}$")
_ARABIC_ANY = r"[\u0600-\u06ff\u0750-\u077f]"          # letters, marks and tatweel
_LATIN_INSIDE_ARABIC = re.compile(_ARABIC_ANY + r"[A-Za-zÀ-ÿ]+" + _ARABIC_ANY)


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[\s\d.,;:!?¿¡«»\"'()\[\]{}\-–—/\\|<>*_=+%&#@]+", text) if w]


def _plausible_arabic(text: str) -> bool:
    """Real Arabic text gives whole Arabic words. A Latin file read as Windows-1256 gets Arabic
    letters inside its own words instead (« École » → « ةcole »), and the two Arabic code pages
    read for each other put Latin letters between Arabic ones (ISO-8859-6 read as Windows-1256:
    « جيتش » → « جêتش »). A French word glued to the article (« الـwifi ») is normal."""
    arabic = [w for w in _words(text) if _ARABIC_LETTER.search(w)]
    mixed = [w for w in arabic if _ASCII_LETTER.search(w)]
    inside = [w for w in arabic if _LATIN_INSIDE_ARABIC.search(w)]
    return (bool(arabic) and len(mixed) <= 0.2 * len(arabic)
            and len(inside) <= 0.02 * len(arabic))


def _plausible_latin(text: str) -> bool:
    """Read as Windows-1252: an Arabic file read this way turns into words made only of
    accented capitals and the like (« ÔäæÉ ÕÇÑ ») instead of words with plain letters."""
    words = [w for w in _words(text) if len(w) >= 3]
    garbled = [w for w in words if _ACCENTED_ONLY.match(w)]
    return len(garbled) <= 0.2 * max(1, len(words))


def _utf16_without_bom(data: bytes) -> str | None:
    """UTF-16 saved without its byte-order mark. Timecodes, numbers and spaces are plain ASCII,
    so in such a file about one byte in two is zero: the odd ones in little-endian order, the
    even ones in big-endian. A few stray zero bytes in another file are damage, not UTF-16."""
    odd, even = data[1::2].count(0), data[0::2].count(0)
    if max(odd, even) < 0.2 * (len(data) // 2):
        return None
    try:
        return data.decode("utf-16-le" if odd >= even else "utf-16-be")
    except UnicodeDecodeError:
        return None


def _decode(data: bytes) -> tuple[str | None, str]:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    if b"\x00" in data:
        # No subtitle text holds a zero byte, but UTF-16 does, and UTF-8 would accept it.
        return _utf16_without_bom(data), "utf-16"
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    arabic = data.decode("cp1256")          # every byte has a character in Windows-1256
    if _plausible_arabic(arabic):
        return arabic, "cp1256"
    try:
        iso = data.decode("iso8859_6")       # the other Arabic code page, older and rarer
    except UnicodeDecodeError:
        iso = None
    if iso is not None and _plausible_arabic(iso):
        return iso, "iso8859_6"
    try:
        latin = data.decode("cp1252")
    except UnicodeDecodeError:
        return None, ""
    return (latin, "cp1252") if _plausible_latin(latin) else (None, "")


def decode_subtitles(data: bytes, name: str = "les sous-titres") -> tuple[str, str]:
    """(text, encoding) for a subtitle file's bytes, never replacing a character it cannot read.

    UTF-16 (with or without its byte-order mark) and UTF-8 are tried first, then Windows-1256,
    the usual encoding of Arabic subtitles made on Windows, ISO-8859-6, then Windows-1252 for
    Latin scripts. These code pages map almost every byte, so each is kept only if the text it
    gives looks like the script it is meant for. Anything else raises SubtitleError with what
    to do."""
    text, encoding = _decode(data)
    if text is None or "\x00" in text:
        raise SubtitleError(
            f"Impossible de lire {name} : ce n'est ni de l'UTF-8, ni de l'UTF-16, ni de l'arabe "
            "en Windows-1256 ou en ISO-8859-6, ni du Windows-1252 (latin). Ouvrez le fichier dans "
            "un éditeur de sous-titres (Subtitle Edit, Aegisub…) et enregistrez-le en UTF-8, puis "
            "relancez Wasf.")
    return text, encoding


def load_subtitles(path: Path) -> tuple[list[Cue], str, list[str]]:
    """Read an SRT or WebVTT file: (cues, encoding found, warnings)."""
    path = Path(path)
    text, encoding = decode_subtitles(path.read_bytes(), str(path))
    warnings = []
    if "�" in text:
        warnings.append(f"{path.name} contient déjà des caractères illisibles (« � ») : le "
                        "fichier a sans doute été abîmé avant Wasf. Ces répliques seront mal "
                        "comprises par l'agent.")
    cues = _parse_text(text)
    if not cues:
        # Nothing read from a file that has text: the pauses would silently come from the
        # silences, possibly over the dialogue. Stop instead; an empty file only warns.
        if re.sub(r"^\s*WEBVTT[^\n]*", "", text.lstrip("﻿")).strip():
            raise SubtitleError(
                f"Aucune réplique lue dans {path} (encodage {ENCODING_NAMES[encoding]}) : ce "
                "n'est pas un fichier SRT ou WebVTT que Wasf sait lire. Vérifiez le fichier, ou "
                "relancez sans --sous-titres : les pauses seront alors cherchées dans les "
                "silences.")
        warnings.append(f"{path.name} ne contient aucune réplique : les pauses seront cherchées "
                        "dans les silences.")
    return cues, encoding, warnings


def parse_subtitles(path: Path) -> list[Cue]:
    """Read an SRT or WebVTT file. Formatting tags are removed. See load_subtitles for the
    encoding that was found."""
    return load_subtitles(path)[0]


def _parse_text(text: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        for i, line in enumerate(lines):
            if "-->" not in line:
                continue
            left, right = line.split("-->", 1)
            try:
                start = parse_tc(left.strip().split()[0])
                end = parse_tc(right.strip().split()[0])
            except (ValueError, IndexError):
                break
            body = " ".join(_TAGS.sub("", part).strip() for part in lines[i + 1:]).strip()
            if end > start:
                cues.append(Cue(start, end, body))
            break
    cues.sort(key=lambda c: c.start)
    return cues


def gaps_from_cues(cues: list[Cue], total: float, min_gap: float = 1.6) -> list[Window]:
    gaps: list[Window] = []
    cursor = 0.0
    for cue in cues:
        if cue.start - cursor >= min_gap:
            gaps.append(Window(cursor, cue.start, "sous-titres"))
        cursor = max(cursor, cue.end)
    if total - cursor >= min_gap:
        gaps.append(Window(cursor, total, "sous-titres"))
    return gaps


_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*([\d.]+)")


def gaps_from_silence(video: Path, total: float, noise_db: float = -30.0,
                      min_gap: float = 1.6) -> list[Window]:
    if not media.has_audio(video):
        return [Window(0.0, total, "silence")]
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vn",
         "-af", f"silencedetect=noise={noise_db}dB:d={min_gap}", "-f", "null", "-"],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    starts = [max(0.0, float(m.group(1))) for m in _SIL_START.finditer(proc.stderr)]
    ends = [float(m.group(1)) for m in _SIL_END.finditer(proc.stderr)]
    gaps = []
    for i, start in enumerate(starts):
        end = min(ends[i] if i < len(ends) else total, total)
        if end - start >= min_gap:
            gaps.append(Window(start, end, "silence"))
    return gaps


def split_long(gaps: list[Window], max_len: float = 8.0) -> list[Window]:
    """Cut long pauses so each description stays short and close to its image."""
    out: list[Window] = []
    for gap in gaps:
        parts = max(1, math.ceil(gap.duration / max_len))
        step = gap.duration / parts
        for k in range(parts):
            out.append(Window(gap.start + k * step, gap.start + (k + 1) * step, gap.source))
    return out


def plan_windows(total: float, cues: list[Cue] | None = None, video: Path | None = None,
                 min_gap: float = 1.6, max_len: float = 8.0) -> list[Window]:
    if cues:
        gaps = gaps_from_cues(cues, total, min_gap)
    elif video is not None:
        gaps = gaps_from_silence(video, total, min_gap=min_gap)
    else:
        gaps = [Window(0.0, total, "silence")]
    return split_long(gaps, max_len)


def neighbours(cues: list[Cue], window: Window) -> tuple[str, str]:
    """Dialogue just before and just after a pause (context for the agent)."""
    before = [c.text for c in cues if c.end <= window.start + 0.05]
    after = [c.text for c in cues if c.start >= window.end - 0.05]
    return (before[-1] if before else "", after[0] if after else "")

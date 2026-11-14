"""Timecode helpers: seconds <-> 'HH:MM:SS.mmm'."""
from __future__ import annotations

import re

_TC = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$")


def parse_tc(value) -> float:
    """Parse seconds or a timecode such as '01:02:03,500', '02:03.5' or '1:30'."""
    if isinstance(value, bool):
        raise ValueError(f"Timecode invalide : {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    match = _TC.match(text)
    if not match:
        raise ValueError(f"Timecode invalide : {value!r}")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int((match.group(4) or "0").ljust(3, "0"))
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def fmt_tc(seconds: float, sep: str = ".") -> str:
    """Format seconds as 'HH:MM:SS.mmm' (use sep=',' for SRT)."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{millis:03d}"


def fmt_short(seconds: float) -> str:
    """Human-friendly 'M:SS,s' used in the editor and in logs."""
    seconds = max(0.0, float(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}:{secs:04.1f}".replace(".", ",")

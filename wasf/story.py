"""What the agent knows of the story before a pause: earlier dialogue and earlier descriptions.

Only the past goes in, so the agent cannot give away what comes later in the film. No extra
model call is made: the context is built from the subtitles and from the descriptions already
drafted, which keeps the energy cost of a film unchanged.
"""
from __future__ import annotations

from .gaps import Cue
from .timecode import fmt_short

MAX_CHARS = 1500   # about 400 tokens: enough for the last few minutes of a scene
MAX_LINE = 280


def _clip(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_LINE else text[: MAX_LINE - 1].rstrip() + "…"


def story_so_far(cues: list[Cue], described: list[tuple[float, str]], before: float,
                 max_chars: int = MAX_CHARS) -> list[str]:
    """Lines, oldest first, for everything that happened before `before` seconds.

    cues: the subtitle cues; described: (start of the pause, text) of descriptions already
    written. When everything does not fit in max_chars, the most recent lines are kept.
    """
    events = [(cue.start, f"{fmt_short(cue.start)} · dialogue : « {_clip(cue.text)} »")
              for cue in cues if cue.end <= before + 0.05 and cue.text.strip()]
    events += [(start, f"{fmt_short(start)} · description : {_clip(text)}")
               for start, text in described if start < before and (text or "").strip()]
    events.sort(key=lambda event: event[0])
    kept: list[str] = []
    size = 0
    for _, line in reversed(events):
        if kept and size + len(line) + 1 > max_chars:
            break
        kept.append(line)
        size += len(line) + 1
    return kept[::-1]

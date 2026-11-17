
from __future__ import annotations

from .textnorm import mentions
from .timecode import fmt_short

MAX_FACTS = 3


def _about(name: str, text: str) -> bool:
    return bool(text) and mentions(text, name)


def character_memory(done, names, max_lines: int = 6) -> list[str]:
    """One line per named character, from the most recent passage where they appear.

    done: the passages already described, in film order (project.Segment)."""
    lines: list[str] = []
    for name in [n for n in names if n and n.strip()]:
        for seg in reversed(done):
            facts = [o for o in seg.observations_ia if _about(name, o)]
            facts += [f"{c['avant']} → {c['apres']}" for c in seg.changements_ia
                      if _about(name, c.get("qui", "")) and c.get("avant") and c.get("apres")]
            facts += [f"{i['geste']} envers {i['envers']}" for i in seg.interactions_ia
                      if _about(name, i.get("qui", "")) and i.get("geste")]
            if not facts and not _about(name, seg.texte):
                continue
            shown = " ; ".join(facts[:MAX_FACTS]) or seg.texte[:120]
            feelings = [e for e in seg.emotions_ia if _about(name, e.get("qui", ""))]
            supposed = ", ".join(
                e["emotion"] + ("" if e.get("certitude") is None
                                else f" ({round(e['certitude'] * 100)} %)") for e in feelings)
            lines.append(f"{name} ({fmt_short(seg.debut)}) : {shown}"
                         + (f" ; supposé : {supposed}" if supposed else ""))
            break
    return lines[:max_lines]

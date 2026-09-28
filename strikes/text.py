"""
Cleaning channel boilerplate out of a post and a cheap keyword gate before the model call.
"""

import re

_INVISIBLE = re.compile("[​‌‍⁠﻿ㅤᅟᅠ­]")
_APOSTROPHES = re.compile("[ʼ’`‘]")
_PROMO_LINE = re.compile(
    r"(@\w+bot\b|надіслати новину|прислать новость|надіслати фото|"
    r"підписатися|подписаться|підписуйтесь|подписывайтесь|"
    r"t\.me/|https?://)",
    re.IGNORECASE,
)
_EMPTY_LINE = re.compile(r"^[\W_]*$")

_STRIKE_WORDS = re.compile(
    r"(влуч|влучан|приліт|прильот|прилет|попадан|попал|"
    r"уламк|обломк|падіння|падени|вибух|взрыв|"
    r"пожеж|пожар|загорян|возгоран|руйнуван|разрушен|"
    r"пошкодж|поврежд|уражен|поражен|удар|детонац|"
    r"збит|збив|сбит|сбив|знешкодж|шахед|дрон|ракет|бпла)",
    re.IGNORECASE,
)


def clean_message(text: str) -> str:
    """Drops invisible fillers, promo/subscribe lines and unifies apostrophes."""
    text = _APOSTROPHES.sub("'", _INVISIBLE.sub("", text or ""))
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if _EMPTY_LINE.match(line) or _PROMO_LINE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def looks_like_strike(text: str) -> bool:
    """Cheap pre-filter so obvious non-reports never reach the model."""
    return bool(_STRIKE_WORDS.search(text or ""))

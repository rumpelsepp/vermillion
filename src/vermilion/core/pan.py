# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pan and balance of stereo mixer cells.

The interfaces have no pan controls: a mixer cell of a stereo mix is a
pair of gains (left and right). Pan (mono input) and balance (stereo
input) are expressed through their ratio, with a balance law that keeps
0 dB in the centre: the level applies to the louder side, the other
side is attenuated linearly in amplitude, down to silence at the end of
the range. In the centre both gains are equal, as for a linked pair
without pan.

Pan is -1 (left) .. 0 (centre) .. 1 (right). Levels are in dB, with
-inf for silence.
"""

import math

NEG_INF = -math.inf


def _amplitude(level_db: float) -> float:
    return 0.0 if level_db == NEG_INF else 10.0 ** (level_db / 20.0)


def _level(amplitude: float) -> float:
    return NEG_INF if amplitude <= 0.0 else 20.0 * math.log10(amplitude)


def split(level_db: float, pan: float) -> tuple[float, float]:
    """(left, right) levels for a level and a pan position."""
    pan = min(1.0, max(-1.0, pan))
    amplitude = _amplitude(level_db)
    left = amplitude * (1.0 - max(pan, 0.0))
    right = amplitude * (1.0 + min(pan, 0.0))
    return _level(left), _level(right)


def combine(left_db: float, right_db: float) -> tuple[float, float | None]:
    """(level, pan) for a pair of levels; pan is None if both are silent."""
    left, right = _amplitude(left_db), _amplitude(right_db)
    if left <= 0.0 and right <= 0.0:
        return NEG_INF, None
    if left >= right:
        return _level(left), -(1.0 - right / left)
    return _level(right), 1.0 - left / right


def format_pan(pan: float) -> str:
    """ "C", "L 30" or "R 100"."""
    percent = round(pan * 100)
    if percent == 0:
        return "C"
    return f"L {-percent}" if percent < 0 else f"R {percent}"


def parse_pan(text: str) -> float | None:
    """A pan position as typed by the user: "C", "L 30", "r100", "-30"
    (left) or "30" (right), in percent, a "%" is allowed; beyond 100 it
    is limited to the end. None if invalid."""
    text = text.strip().lower().replace("−", "-").replace(" ", "").removesuffix("%")
    if text in ("c", "center", "centre"):
        return 0.0
    sign = 1.0
    if text[:1] in ("l", "r"):
        sign = -1.0 if text[0] == "l" else 1.0
        text = text[1:]
        if text.startswith(("-", "+")):
            return None
    try:
        value = float(text)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return min(1.0, max(-1.0, sign * value / 100.0))

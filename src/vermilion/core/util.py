# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small helpers: string parsing, C-compatible rounding, debug flags."""

import math
import re

_NUM_RE = re.compile(r"\d+")


def get_num_from_string(s: str) -> int:
    """Return the first number found in the string, or -1 if none."""
    m = _NUM_RE.search(s)
    return int(m.group()) if m else -1


def parse_int_prefix(text: str) -> tuple[int | None, str]:
    """strtol()-like: a leading integer (None if there is none) and the
    rest of the text."""
    text = text.strip()
    end = 0
    if end < len(text) and text[end] in "+-":
        end += 1
    start_digits = end
    while end < len(text) and text[end].isdigit():
        end += 1
    if end == start_digits:
        return None, text
    return int(text[:end]), text[end:]


def get_two_nums_from_string(s: str) -> tuple[int, int]:
    """Return the first two numbers found in the string (-1 if missing)."""
    nums = _NUM_RE.findall(s)
    a = int(nums[0]) if nums else -1
    b = int(nums[1]) if len(nums) > 1 else -1
    return a, b


def c_round(x: float) -> int:
    """Round half away from zero, like C round()/lround()."""
    return math.floor(abs(x) + 0.5) * (1 if x >= 0 else -1)


def clamp[T: (int, float)](x: T, lo: T, hi: T) -> T:
    return lo if x < lo else min(x, hi)


def bytes_to_str(data: bytes | bytearray | None) -> str:
    """Decode a NUL-terminated UTF-8 byte string; "" if empty/invalid."""
    if not data:
        return ""
    data = bytes(data).split(b"\0", 1)[0]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return ""

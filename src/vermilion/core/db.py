# SPDX-FileCopyrightText: 2024-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parsing dB values typed by the user (the conversion between element
values and dB is done by Elem)."""

import math

_SILENCE = {"-inf", "inf", "-∞", "∞", "off", "mute"}


def parse_db(text: str) -> float | None:
    """A dB value as typed by the user: "-6", "−6dB", "+2.5", "2,5 dB";
    "-inf", "−∞", "off" or "mute" for silence (-inf). None if invalid."""
    text = text.strip().lower().replace("−", "-").replace(",", ".").replace(" ", "")
    text = text.removesuffix("db")
    if text in _SILENCE:
        return -math.inf
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None

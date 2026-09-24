# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pan/balance law of stereo mixer cells."""

import math

import pytest

from vermilion.core import pan


def test_centre_keeps_level_on_both_sides() -> None:
    assert pan.split(-6.0, 0.0) == pytest.approx((-6.0, -6.0))


def test_full_pan_silences_other_side() -> None:
    assert pan.split(0.0, -1.0) == (0.0, -math.inf)
    assert pan.split(0.0, 1.0) == (-math.inf, 0.0)


def test_half_pan_is_minus_6_db() -> None:
    left, right = pan.split(0.0, 0.5)
    assert left == pytest.approx(20 * math.log10(0.5))
    assert right == pytest.approx(0.0)


@pytest.mark.parametrize("level", [-40.0, -12.5, 0.0, 6.0])
@pytest.mark.parametrize("position", [-1.0, -0.7, -0.25, 0.0, 0.1, 0.5, 1.0])
def test_roundtrip(level: float, position: float) -> None:
    got_level, got_pan = pan.combine(*pan.split(level, position))
    assert got_level == pytest.approx(level)
    assert got_pan == pytest.approx(position)


def test_silence_has_no_pan() -> None:
    assert pan.combine(-math.inf, -math.inf) == (-math.inf, None)


def test_clamps_pan() -> None:
    assert pan.split(0.0, 3.0) == pan.split(0.0, 1.0)


@pytest.mark.parametrize(
    ("position", "text"), [(0.0, "C"), (0.004, "C"), (-0.3, "L 30"), (1.0, "R 100")]
)
def test_format(position: float, text: str) -> None:
    assert pan.format_pan(position) == text


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("C", 0.0),
        (" centre ", 0.0),
        ("0", 0.0),
        ("L 30", -0.3),
        ("l30", -0.3),
        ("R100", 1.0),
        ("r 50 %", 0.5),
        ("-25", -0.25),
        ("−25", -0.25),
        ("+40", 0.4),
        ("L 150", -1.0),
    ],
)
def test_parse_pan(text: str, value: float) -> None:
    assert pan.parse_pan(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["", "x", "L", "L-30", "inf", "nan"])
def test_parse_pan_invalid(text: str) -> None:
    assert pan.parse_pan(text) is None

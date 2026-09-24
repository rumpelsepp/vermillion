# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parsing typed dB values."""

import math

import pytest

from vermilion.core.db import parse_db


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("-6", -6.0),
        ("−6dB", -6.0),
        (" -6 dB ", -6.0),
        ("+2.5", 2.5),
        ("2,5", 2.5),
        ("0", 0.0),
        ("-12.3DB", -12.3),
        ("−∞", -math.inf),
        ("-inf", -math.inf),
        ("off", -math.inf),
        ("Mute", -math.inf),
    ],
)
def test_parse(text: str, value: float) -> None:
    assert parse_db(text) == value


@pytest.mark.parametrize("text", ["", "abc", "dB", "1e999", "nan", "--3"])
def test_invalid(text: str) -> None:
    assert parse_db(text) is None

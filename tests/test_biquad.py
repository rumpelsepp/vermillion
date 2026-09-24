# SPDX-FileCopyrightText: 2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Round-trip tests for biquad design and analysis (port of test-biquad.c)."""

from collections.abc import Iterator

import pytest

from vermilion.core import biquad
from vermilion.core.biquad import GAIN_DB_LIMIT, FilterType

SAMPLE_RATE = 48000.0
FREQS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 15000, 20000]
QS = [0.1, 0.5, 0.707, 1.0, 2.0, 5.0, 10.0]
GAINS = [-GAIN_DB_LIMIT, -18, -12, -6, -3, 0, 3, 6, 12, 18, GAIN_DB_LIMIT]


def _cases() -> Iterator[tuple[FilterType, float, float, float]]:
    for t in FilterType:
        if t == FilterType.GAIN:
            for g in GAINS:
                yield t, 1000, 0.707, g
            continue
        if not biquad.uses_q(t):
            for f in FREQS:
                if biquad.uses_gain(t):
                    for g in GAINS:
                        if g != 0:  # 0 dB shelf is indistinguishable from bypass
                            yield t, f, 0.707, g
                else:
                    yield t, f, 0.707, 0
            continue
        for f in FREQS:
            for q in QS:
                if biquad.uses_gain(t):
                    for g in GAINS:
                        if g == 0 and t in (FilterType.LOW_SHELF, FilterType.HIGH_SHELF):
                            continue
                        yield t, f, q, g
                else:
                    yield t, f, q, 0


@pytest.mark.parametrize("t,freq,q,gain", list(_cases()))
def test_roundtrip(t: FilterType, freq: float, q: float, gain: float) -> None:
    orig = biquad.Params(t, freq, q, gain)
    result = biquad.analyze(biquad.calculate(orig, SAMPLE_RATE), SAMPLE_RATE)

    assert result.type == t
    if t != FilterType.GAIN:
        assert abs(result.freq - freq) < freq * 1e-9
    if biquad.uses_q(t):
        assert abs(result.q - q) < q * 1e-9
    if biquad.uses_gain(t):
        assert abs(result.gain_db - gain) < 1e-8


def test_fixed_point_roundtrip() -> None:
    p = biquad.Params(FilterType.PEAKING, 1000, 1.0, 6)
    c = biquad.calculate(p, SAMPLE_RATE)
    back = biquad.from_fixed_point(biquad.to_fixed_point(c))
    assert abs(back.b0 - c.b0) < 1e-8
    assert abs(back.a2 - c.a2) < 1e-8


def test_identity_is_bypass() -> None:
    p = biquad.analyze(biquad.from_fixed_point(biquad.IDENTITY_FIXED), SAMPLE_RATE)
    assert p.type == FilterType.GAIN and p.gain_db == 0.0

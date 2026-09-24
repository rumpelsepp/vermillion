# SPDX-FileCopyrightText: 2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Biquad filter design (Audio EQ Cookbook), response and analysis.

Reference: https://www.w3.org/TR/audio-eq-cookbook/
"""

import math
from dataclasses import dataclass
from enum import IntEnum

from vermilion.core.util import c_round, clamp


class FilterType(IntEnum):
    PEAKING = 0
    LOW_SHELF = 1
    HIGH_SHELF = 2
    LOWPASS = 3
    HIGHPASS = 4
    BANDPASS = 5
    NOTCH = 6
    GAIN = 7
    # first-order filters (6 dB/octave)
    LOWPASS_1 = 8
    HIGHPASS_1 = 9
    LOW_SHELF_1 = 10
    HIGH_SHELF_1 = 11


TYPE_NAMES = [
    "Peaking",
    "Low Shelf",
    "High Shelf",
    "Lowpass",
    "Highpass",
    "Bandpass",
    "Notch",
    "Gain",
    "LP 6dB/oct",
    "HP 6dB/oct",
    "LS 6dB/oct",
    "HS 6dB/oct",
]

GAIN_DB_LIMIT = 24.0
DB_RANGE_NARROW = 12.0

FIXED_POINT_SHIFT = 28
FIXED_POINT_SCALE = 1 << FIXED_POINT_SHIFT

# tolerance for fixed-point round-trip (2^-28 ~ 3.7e-9, with margin)
_COEFF_TOL = 1e-6


@dataclass
class Params:
    type: FilterType = FilterType.PEAKING
    freq: float = 1000.0  # Hz (20-20000)
    q: float = 0.707  # 0.1-10
    gain_db: float = 0.0  # for peaking/shelving/gain

    def copy(self) -> Params:
        return Params(self.type, self.freq, self.q, self.gain_db)


@dataclass
class Coeffs:
    """Normalised so that a0 = 1."""

    b0: float = 1.0
    b1: float = 0.0
    b2: float = 0.0
    a1: float = 0.0
    a2: float = 0.0


def uses_gain(t: FilterType) -> bool:
    return t in (
        FilterType.PEAKING,
        FilterType.LOW_SHELF,
        FilterType.HIGH_SHELF,
        FilterType.GAIN,
        FilterType.LOW_SHELF_1,
        FilterType.HIGH_SHELF_1,
    )


def uses_q(t: FilterType) -> bool:
    # first-order filters and gain don't use Q
    return t not in (
        FilterType.GAIN,
        FilterType.LOWPASS_1,
        FilterType.HIGHPASS_1,
        FilterType.LOW_SHELF_1,
        FilterType.HIGH_SHELF_1,
    )


def calculate(params: Params, sample_rate: float) -> Coeffs:
    t = params.type
    w0 = 2.0 * math.pi * params.freq / sample_rate
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * params.q)
    A = 10.0 ** (params.gain_db / 40.0)

    if t == FilterType.PEAKING:
        b0, b1, b2 = 1 + alpha * A, -2 * cos_w0, 1 - alpha * A
        a0, a1, a2 = 1 + alpha / A, -2 * cos_w0, 1 - alpha / A
    elif t == FilterType.LOW_SHELF:
        sa = 2 * math.sqrt(A) * alpha
        b0 = A * ((A + 1) - (A - 1) * cos_w0 + sa)
        b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
        b2 = A * ((A + 1) - (A - 1) * cos_w0 - sa)
        a0 = (A + 1) + (A - 1) * cos_w0 + sa
        a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
        a2 = (A + 1) + (A - 1) * cos_w0 - sa
    elif t == FilterType.HIGH_SHELF:
        sa = 2 * math.sqrt(A) * alpha
        b0 = A * ((A + 1) + (A - 1) * cos_w0 + sa)
        b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
        b2 = A * ((A + 1) + (A - 1) * cos_w0 - sa)
        a0 = (A + 1) - (A - 1) * cos_w0 + sa
        a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
        a2 = (A + 1) - (A - 1) * cos_w0 - sa
    elif t == FilterType.LOWPASS:
        b0, b1, b2 = (1 - cos_w0) / 2, 1 - cos_w0, (1 - cos_w0) / 2
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif t == FilterType.HIGHPASS:
        b0, b1, b2 = (1 + cos_w0) / 2, -(1 + cos_w0), (1 + cos_w0) / 2
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif t == FilterType.BANDPASS:
        # constant skirt gain, peak gain = Q
        b0, b1, b2 = alpha, 0.0, -alpha
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif t == FilterType.NOTCH:
        b0, b1, b2 = 1.0, -2 * cos_w0, 1.0
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif t == FilterType.GAIN:
        # pure gain; 20*log10 scale (not 40 like the peaking A parameter)
        return Coeffs(10.0 ** (params.gain_db / 20.0), 0, 0, 0, 0)
    elif t == FilterType.LOWPASS_1:
        K = math.tan(math.pi * params.freq / sample_rate)
        norm = 1 / (1 + K)
        return Coeffs(K * norm, K * norm, 0, (K - 1) * norm, 0)
    elif t == FilterType.HIGHPASS_1:
        K = math.tan(math.pi * params.freq / sample_rate)
        norm = 1 / (1 + K)
        return Coeffs(norm, -norm, 0, (K - 1) * norm, 0)
    elif t == FilterType.LOW_SHELF_1:
        # ensure exact relationship b0 - b1 = 1 - a1 (Nyquist gain = 1)
        K = math.tan(math.pi * params.freq / sample_rate)
        V = 10.0 ** (abs(params.gain_db) / 20.0)
        if params.gain_db >= 0:
            denom = 1 + K
            a1 = (K - 1) / denom
            dc_sum = 2 * V * K / denom
        else:
            denom = 1 + V * K
            a1 = (V * K - 1) / denom
            dc_sum = 2 * K / denom
        nyq_diff = 1 - a1
        return Coeffs((dc_sum + nyq_diff) / 2, (dc_sum - nyq_diff) / 2, 0, a1, 0)
    elif t == FilterType.HIGH_SHELF_1:
        # ensure exact relationship b0 + b1 = 1 + a1 (DC gain = 1)
        K = math.tan(math.pi * params.freq / sample_rate)
        V = 10.0 ** (abs(params.gain_db) / 20.0)
        if params.gain_db >= 0:
            denom = 1 + K
            a1 = (K - 1) / denom
            nyq_diff = 2 * V / denom
        else:
            denom = V + K
            a1 = (K - V) / denom
            nyq_diff = 2 / denom
        dc_sum = 1 + a1
        return Coeffs((dc_sum + nyq_diff) / 2, (dc_sum - nyq_diff) / 2, 0, a1, 0)
    else:
        return Coeffs()

    return Coeffs(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def to_fixed_point(c: Coeffs) -> list[int]:
    """Hardware format: [b0, b1, b2, -a1, -a2] * 2^28."""
    s = FIXED_POINT_SCALE
    return [
        c_round(c.b0 * s),
        c_round(c.b1 * s),
        c_round(c.b2 * s),
        c_round(-c.a1 * s),
        c_round(-c.a2 * s),
    ]


def from_fixed_point(fixed: list[int]) -> Coeffs:
    s = FIXED_POINT_SCALE
    return Coeffs(fixed[0] / s, fixed[1] / s, fixed[2] / s, -fixed[3] / s, -fixed[4] / s)


IDENTITY_FIXED = [FIXED_POINT_SCALE, 0, 0, 0, 0]


def response_db(c: Coeffs, freq: float, sample_rate: float) -> float:
    """Magnitude of H(z) at freq, in dB."""
    w = 2.0 * math.pi * freq / sample_rate
    cos_w, cos_2w = math.cos(w), math.cos(2 * w)
    sin_w, sin_2w = math.sin(w), math.sin(2 * w)

    num_re = c.b0 + c.b1 * cos_w + c.b2 * cos_2w
    num_im = -c.b1 * sin_w - c.b2 * sin_2w
    den_re = 1.0 + c.a1 * cos_w + c.a2 * cos_2w
    den_im = -c.a1 * sin_w - c.a2 * sin_2w

    num_sq = num_re * num_re + num_im * num_im
    den_sq = den_re * den_re + den_im * den_im
    if den_sq < 1e-20:
        return 0.0
    mag_sq = num_sq / den_sq
    if mag_sq < 1e-20:
        return -100.0
    return 10.0 * math.log10(mag_sq)


def _eq(a: float, b: float, tol: float = _COEFF_TOL) -> bool:
    return abs(a - b) < tol


def _q_from_alpha(sin_w0: float, alpha: float, default: float) -> float:
    q = sin_w0 / (2 * alpha) if alpha > 1e-10 else default
    return clamp(q, 0.1, 10.0)


def analyze(c: Coeffs, sample_rate: float) -> Params:
    """Recover filter parameters from coefficients."""
    b0, b1, b2, a1, a2 = c.b0, c.b1, c.b2, c.a1, c.a2
    p = Params()

    # pure gain filter
    if (
        _eq(b1, 0, 0.001)
        and _eq(b2, 0, 0.001)
        and _eq(a1, 0, 0.001)
        and _eq(a2, 0, 0.001)
        and b0 > 0
    ):
        p.type = FilterType.GAIN
        p.freq, p.q = 1000.0, 0.707
        p.gain_db = clamp(20 * math.log10(b0), -GAIN_DB_LIMIT, GAIN_DB_LIMIT)
        return p

    # first-order filters (b2 = 0, a2 = 0)
    if _eq(b2, 0, 0.001) and _eq(a2, 0, 0.001):
        K = max((1 + a1) / (1 - a1), 0.001)
        p.freq = clamp(math.atan(K) * sample_rate / math.pi, 20.0, 20000.0)
        p.q = 0.707

        if _eq(b0, b1):
            p.type, p.gain_db = FilterType.LOWPASS_1, 0.0
            return p
        if _eq(b0, -b1):
            p.type, p.gain_db = FilterType.HIGHPASS_1, 0.0
            return p

        if _eq(b0 - b1, 1 - a1):
            p.type = FilterType.LOW_SHELF_1
            dc_gain = (b0 + b1) / (1 + a1)
            p.gain_db = clamp(20 * math.log10(abs(dc_gain)), -24.0, 24.0)
            V = 10 ** (abs(p.gain_db) / 20)
            K_term = (1 + a1) / (1 - a1)
            K = K_term if p.gain_db >= 0 else K_term / V
            if K > 0:
                p.freq = math.atan(K) * sample_rate / math.pi
            p.freq = clamp(p.freq, 20.0, 20000.0)
            return p

        if _eq(b0 + b1, 1 + a1):
            p.type = FilterType.HIGH_SHELF_1
            nyq_gain = (b0 - b1) / (1 - a1)
            p.gain_db = clamp(20 * math.log10(abs(nyq_gain)), -24.0, 24.0)
            V = 10 ** (abs(p.gain_db) / 20)
            K_term = (1 + a1) / (1 - a1)
            K = K_term if p.gain_db >= 0 else K_term * V
            if K > 0:
                p.freq = math.atan(K) * sample_rate / math.pi
            p.freq = clamp(p.freq, 20.0, 20000.0)
            return p

        p.type, p.gain_db = FilterType.LOWPASS_1, 0.0
        return p

    # For all second-order types a0 = 2/(1+a2), so cos_w0 = -a1*a0/2
    a0 = 2.0 / (1.0 + a2)
    cos_w0 = clamp(-a1 * a0 / 2.0, -1.0, 1.0)
    w0 = math.acos(cos_w0)
    sin_w0 = math.sin(w0)
    p.freq = clamp(w0 * sample_rate / (2 * math.pi), 20.0, 20000.0)
    p.gain_db = 0.0

    dc_gain = (b0 + b1 + b2) / (1 + a1 + a2)
    nyq_gain = (b0 - b1 + b2) / (1 - a1 + a2)

    # low shelf: DC gain != 1, Nyquist ~ 1 (exclude highpass with dc ~ 0)
    if abs(dc_gain - 1) > 0.05 and abs(dc_gain) > 0.01 and _eq(nyq_gain, 1.0, 0.1):
        p.type = FilterType.LOW_SHELF
        p.gain_db = clamp(20 * math.log10(abs(dc_gain)), -GAIN_DB_LIMIT, GAIN_DB_LIMIT)
        A = math.sqrt(abs(dc_gain))
        num = -(a1 * (A + 1) + (1 + a2) * (A - 1))
        den = a1 * (A - 1) + (1 + a2) * (A + 1)
        shelf_cos = 0.0
        if abs(den) > 0.001:
            shelf_cos = clamp(num / den, -1.0, 1.0)
            p.freq = math.acos(shelf_cos) * sample_rate / (2 * math.pi)
        shelf_sin = math.sqrt(1 - shelf_cos * shelf_cos)
        x = (A + 1) + (A - 1) * shelf_cos
        y_over_x = (1 - a2) / (1 + a2)
        p.q = math.sqrt(A) * shelf_sin / (y_over_x * x) if abs(y_over_x * x) > 1e-10 else 0.707
        p.q = clamp(p.q, 0.1, 10.0)
        return p

    # high shelf: Nyquist gain != 1, DC ~ 1 (exclude lowpass)
    if abs(nyq_gain - 1) > 0.05 and abs(nyq_gain) > 0.01 and _eq(dc_gain, 1.0, 0.1):
        p.type = FilterType.HIGH_SHELF
        p.gain_db = clamp(20 * math.log10(abs(nyq_gain)), -GAIN_DB_LIMIT, GAIN_DB_LIMIT)
        A = math.sqrt(abs(nyq_gain))
        num = a1 * (A + 1) - (1 + a2) * (A - 1)
        den = a1 * (A - 1) - (1 + a2) * (A + 1)
        shelf_cos = 0.0
        if abs(den) > 0.001:
            shelf_cos = clamp(num / den, -1.0, 1.0)
            p.freq = math.acos(shelf_cos) * sample_rate / (2 * math.pi)
        shelf_sin = math.sqrt(1 - shelf_cos * shelf_cos)
        x = (A + 1) - (A - 1) * shelf_cos
        y_over_x = (1 - a2) / (1 + a2)
        p.q = math.sqrt(A) * shelf_sin / (y_over_x * x) if abs(y_over_x * x) > 1e-10 else 0.707
        p.q = clamp(p.q, 0.1, 10.0)
        return p

    # bandpass: b1 = 0, b0 = -b2
    if _eq(b1, 0) and _eq(b0, -b2):
        p.type = FilterType.BANDPASS
        p.q = _q_from_alpha(sin_w0, (1 - a2) / (1 + a2), 1.0)
        return p

    # peaking: b1 = a1, b0 != b2
    if _eq(b1, a1) and not _eq(b0, b2):
        p.type = FilterType.PEAKING
        b_diff = b0 - b2
        a_diff = 1 - a2
        A_sq = b_diff / a_diff
        A = math.sqrt(A_sq) if A_sq > 0 and math.isfinite(A_sq) else 1.0
        alpha_sq = b_diff * a_diff / ((1 + a2) * (1 + a2))
        alpha = math.sqrt(alpha_sq) if alpha_sq > 0 else 0.001
        p.gain_db = clamp(40 * math.log10(A), -GAIN_DB_LIMIT, GAIN_DB_LIMIT)
        p.q = _q_from_alpha(sin_w0, alpha, 1.0)
        return p

    # notch: b0 = b2, b1 = a1
    if _eq(b0, b2) and _eq(b1, a1):
        p.type = FilterType.NOTCH
        p.q = _q_from_alpha(sin_w0, (1 - a2) / (1 + a2), 1.0)
        return p

    # lowpass: b0 = b2, b1 = 2*b0
    if _eq(b0, b2) and _eq(b1, 2 * b0):
        p.type = FilterType.LOWPASS
        p.q = _q_from_alpha(sin_w0, (1 - a2) / (1 + a2), 0.707)
        return p

    # highpass: b0 = b2, b1 = -2*b0
    if _eq(b0, b2) and _eq(b1, -2 * b0):
        p.type = FilterType.HIGHPASS
        p.q = _q_from_alpha(sin_w0, (1 - a2) / (1 + a2), 0.707)
        return p

    # default to 0 dB gain (equivalent to bypass)
    return Params(FilterType.GAIN, 1000.0, 0.707, 0.0)

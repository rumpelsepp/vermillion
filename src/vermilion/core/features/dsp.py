# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""DSP (Vocaster): filter stages, compressor, presets and channel linking.

The hardware only stores biquad coefficients; the filter parameters
(type, frequency, Q, gain) the user chose are kept in simulated
elements persisted in the state file, so that a disabled stage keeps
its settings.
"""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, ClassVar, Self

from gi.repository import GObject

from vermilion.core import biquad
from vermilion.core.asound import ELEM_TYPE_BOOLEAN, ELEM_TYPE_ENUMERATED, ELEM_TYPE_INTEGER
from vermilion.core.biquad import GAIN_DB_LIMIT, FilterType, Params
from vermilion.core.constants import PC
from vermilion.core.signals import SignalSpec, signal
from vermilion.core.storage import state
from vermilion.core.util import clamp

if TYPE_CHECKING:
    from vermilion.core.card import Card, Elem
    from vermilion.core.ports import RoutingSnk, RoutingSrc

SAMPLE_RATE = 48000.0

# scaling factors for storing float values as integers
FREQ_SCALE = 10  # Hz * 10
Q_SCALE = 1000  # Q * 1000
GAIN_SCALE = 10  # dB * 10

LINK_ELEM_NAME = "DSP 1-2 Link"

PRECOMP_STAGES = 2
PEQ_BANDS = 3

COMPRESSOR_PARAMS = [
    "Compressor Threshold",
    "Compressor Ratio",
    "Compressor Knee Width",
    "Compressor Attack",
    "Compressor Release",
    "Compressor Makeup Gain",
]

# pre-comp presets: (name, stage 1 coefficients, stage 2 coefficients)
PRECOMP_PRESETS: list[tuple[str, list[int], list[int]]] = [
    ("None", [268435456, 0, 0, 0, 0], [268435456, 0, 0, 0, 0]),
    (
        "Rumble Reduction Low",
        [266497594, -532995188, 266497594, 532986969, -264567952],
        [267626948, -535253896, 267626948, 535245642, -266826694],
    ),
    (
        "Rumble Reduction High",
        [265856028, -531712056, 265856028, 531697479, -263291177],
        [267356697, -534713394, 267356697, 534698735, -266292598],
    ),
]

# compressor presets: name, threshold (dB), ratio (x2), knee (dB),
# attack (ms), release (ms), makeup (dB)
type CompressorPreset = tuple[str, int, int, int, int, int, int]

COMPRESSOR_PRESETS: list[CompressorPreset] = [
    ("Off", 0, 8, 3, 10, 30, 0),
    ("Low", -10, 8, 3, 10, 30, 2),
    ("Med", -20, 8, 3, 10, 30, 3),
    ("High", -30, 8, 3, 10, 30, 5),
]

# PEQ presets: (name, band 1, band 2, band 3 coefficients)
PEQ_PRESETS: list[tuple[str, list[int], list[int], list[int]]] = [
    (
        "Radio",
        [268764056, -534822977, 266136367, 534822977, -266464967],
        [264343107, -475942323, 220923477, 475942323, -216831129],
        [280826929, -286659621, 124570994, 286659621, -136962468],
    ),
    (
        "Clean",
        [268173186, -534243182, 266147357, 534243182, -265885087],
        [273994701, -484439285, 219935310, 484439285, -225494556],
        [285089098, -288665257, 123145223, 288665257, -139798866],
    ),
    (
        "Warm",
        [268304503, -534385186, 266158065, 534385186, -266027113],
        [275408969, -485541124, 219644468, 485541124, -226617981],
        [260481651, -276190834, 130111172, 276190834, -122157368],
    ),
    (
        "Bright",
        [268173186, -534243182, 266147357, 534243182, -265885087],
        [276834931, -486616512, 219314962, 486616512, -227714437],
        [293825201, -292586874, 119955124, 292586874, -145344869],
    ),
]


def filter_elem_name(filter_type: str, channel: int, stage: int, param: str) -> str:
    return f"Line In {channel} {filter_type} Filter {stage} {param}"


# filter stage model


class FilterStage(GObject.Object):
    """One biquad stage (pre-comp filter or PEQ band) of one channel.

    Emits "changed"(params_changed) when params/enabled changed from
    outside the UI.
    """

    __gsignals__: ClassVar[dict[str, SignalSpec]] = {
        "changed": signal(bool),
    }

    def __init__(
        self,
        card: Card,
        coeff_elem: Elem,
        filter_type: str,
        channel: int,
        stage_num: int,
        default_type: FilterType,
    ) -> None:
        super().__init__()
        self.card = card
        self.coeff_elem = coeff_elem
        self.enabled = True
        self.params = Params(default_type, 1000.0, 0.707, 0.0)
        self._last_ui_coeffs: list[int] | None = None
        self._updating_from_state = False
        self._connections: list[tuple[Elem, int]] = []

        def n(param: str) -> Elem | None:
            return card.elem(filter_elem_name(filter_type, channel, stage_num, param))

        self.state_enable = n("Enable")
        self.state_type = n("Type")
        self.state_freq = n("Freq")
        self.state_q = n("Q")
        self.state_gain = n("Gain")

        # analyse the existing hardware coefficients
        p = biquad.analyze(biquad.from_fixed_point(coeff_elem.get_int_values()), SAMPLE_RATE)
        if p.type == FilterType.GAIN and p.gain_db == 0.0:
            # bypass: load the saved parameters instead
            self.enabled = False
            if self.state_type:
                p.type = FilterType(self.state_type.get_value())
            if self.state_freq:
                p.freq = self.state_freq.get_value() / FREQ_SCALE
            if self.state_q:
                p.q = self.state_q.get_value() / Q_SCALE
            if self.state_gain:
                p.gain_db = self.state_gain.get_value() / GAIN_SCALE
            p.freq = clamp(p.freq, 20.0, 20000.0)
            p.q = clamp(p.q, 0.1, 10.0)
            p.gain_db = clamp(p.gain_db, -GAIN_DB_LIMIT, GAIN_DB_LIMIT)
        self.params = p

        self.save_state()

        self._connect(coeff_elem, self._coeffs_updated)
        for elem, fn in (
            (self.state_enable, self._state_enable_updated),
            (self.state_type, self._state_type_updated),
            (self.state_freq, self._state_freq_updated),
            (self.state_q, self._state_q_updated),
            (self.state_gain, self._state_gain_updated),
        ):
            if elem:
                self._connect(elem, fn)

    def _connect(self, elem: Elem, fn: Callable[[Elem], None]) -> None:
        self._connections.append((elem, elem.connect("changed", fn)))

    def close(self) -> None:
        for elem, handler_id in self._connections:
            elem.disconnect(handler_id)
        self._connections = []

    # hardware / state updates

    def fixed_coeffs(self) -> list[int]:
        if not self.enabled:
            return list(biquad.IDENTITY_FIXED)
        return biquad.to_fixed_point(biquad.calculate(self.params, SAMPLE_RATE))

    def coeffs(self) -> biquad.Coeffs:
        return biquad.calculate(self.params, SAMPLE_RATE)

    def update_coeffs(self) -> None:
        fixed = self.fixed_coeffs()
        self._last_ui_coeffs = fixed
        self.coeff_elem.set_int_values(fixed)

    def _save_param(self, elem: Elem | None, value: int) -> None:
        if not elem:
            return
        elem.value = int(value)
        self.card.state.save(state.SECTION_CONTROLS, elem.name, str(int(value)))

    def save_state(self) -> None:
        p = self.params
        self._save_param(self.state_enable, 1 if self.enabled else 0)
        self._save_param(self.state_type, int(p.type))
        self._save_param(self.state_freq, int(p.freq * FREQ_SCALE))
        self._save_param(self.state_q, int(p.q * Q_SCALE))
        self._save_param(self.state_gain, int(p.gain_db * GAIN_SCALE))

    # user changes

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self.update_coeffs()
        self.save_state()

    def set_type(self, filter_type: FilterType) -> None:
        self.params.type = FilterType(filter_type)
        self.update_coeffs()
        self.save_state()

    def set_params(
        self, freq: float | None = None, q: float | None = None, gain_db: float | None = None
    ) -> None:
        if freq is not None:
            self.params.freq = clamp(freq, 20.0, 20000.0)
        if q is not None:
            self.params.q = clamp(q, 0.1, 10.0)
        if gain_db is not None:
            self.params.gain_db = clamp(gain_db, -GAIN_DB_LIMIT, GAIN_DB_LIMIT)
        self.update_coeffs()
        self.save_state()

    # external changes

    def _coeffs_updated(self, elem: Elem) -> None:
        fixed = elem.get_int_values()
        if fixed == self._last_ui_coeffs:
            return
        new = biquad.analyze(biquad.from_fixed_point(fixed), SAMPLE_RATE)
        enabled = not (new.type == FilterType.GAIN and new.gain_db == 0.0)
        # if disabled, keep the previous parameters for the UI
        if enabled:
            self.params = new
        self.enabled = enabled
        if not self._updating_from_state:
            self.save_state()
        self.emit("changed", True)

    def _from_state(self) -> None:
        self._updating_from_state = True
        self.update_coeffs()
        self._updating_from_state = False
        self.emit("changed", False)

    def _state_enable_updated(self, elem: Elem) -> None:
        self.enabled = bool(elem.get_value())
        self._from_state()

    def _state_type_updated(self, elem: Elem) -> None:
        t = elem.get_value()
        if 0 <= t < len(biquad.TYPE_NAMES):
            self.params.type = FilterType(t)
            self._from_state()

    def _state_freq_updated(self, elem: Elem) -> None:
        self.params.freq = clamp(elem.get_value() / FREQ_SCALE, 20.0, 20000.0)
        self._from_state()

    def _state_q_updated(self, elem: Elem) -> None:
        self.params.q = clamp(elem.get_value() / Q_SCALE, 0.1, 10.0)
        self._from_state()

    def _state_gain_updated(self, elem: Elem) -> None:
        self.params.gain_db = clamp(elem.get_value() / GAIN_SCALE, -GAIN_DB_LIMIT, GAIN_DB_LIMIT)
        self._from_state()


def apply_coeff_preset(elems: Sequence[Elem | None], coeff_sets: Sequence[list[int]]) -> None:
    for elem, coeffs in zip(elems, coeff_sets):
        if elem:
            elem.set_int_values(coeffs)


def compressor_output(
    threshold: float, ratio_x2: float, knee: float, makeup: float, input_db: float
) -> float:
    """Static compressor curve: output level (dB) for an input level."""
    ratio = ratio_x2 / 2.0
    if knee <= 0:
        out = input_db if input_db < threshold else threshold + (input_db - threshold) / ratio
    elif input_db < threshold - knee / 2:
        out = input_db
    elif input_db > threshold + knee / 2:
        out = threshold + (input_db - threshold) / ratio
    else:
        x = input_db - threshold + knee / 2
        out = input_db - (1.0 - 1.0 / ratio) * x * x / (2.0 * knee)
    return out + makeup


# the DSP of a card


class DspChannel:
    """The DSP of one input channel (1 or 2): its elements, the simulated
    ones for the filter parameters included."""

    def __init__(self, card: Card, number: int) -> None:
        self.card = card
        self.number = number

    def elem(self, name: str) -> Elem | None:
        return self.card.elem(f"Line In {self.number} {name}")

    @property
    def precomp_coeffs(self) -> list[Elem | None]:
        return [self.elem(f"Pre-Comp Coefficients {i}") for i in range(1, PRECOMP_STAGES + 1)]

    @property
    def peq_coeffs(self) -> list[Elem | None]:
        return [self.elem(f"PEQ Coefficients {i}") for i in range(1, PEQ_BANDS + 1)]

    def apply_compressor_preset(self, preset: CompressorPreset) -> None:
        _, *values = preset
        for name, value in zip(COMPRESSOR_PARAMS, values):
            elem = self.elem(name)
            if elem:
                elem.set_value(value)

    @property
    def src(self) -> RoutingSrc | None:
        """The DSP output routing source (for names and levels)."""
        for src in self.card.routing_srcs:
            if src.port_category == PC.DSP and src.port_num == self.number - 1:
                return src
        return None

    @property
    def snk(self) -> RoutingSnk | None:
        for snk in self.card.routing_snks:
            if snk.elem.port_category == PC.DSP and snk.elem.port_num == self.number - 1:
                return snk
        return None

    def create_elems(self) -> None:
        """The simulated filter parameter elements."""
        for stage in range(1, PRECOMP_STAGES + 1):
            self._create_stage_elems("Pre-Comp", stage, FilterType.HIGHPASS)
        for stage in range(1, PEQ_BANDS + 1):
            self._create_stage_elems("PEQ", stage, FilterType.PEAKING)

    def _create_stage_elems(self, filter_type: str, stage: int, default_type: FilterType) -> None:
        card = self.card

        def n(param: str) -> str:
            return filter_elem_name(filter_type, self.number, stage, param)

        card.optional_elem(n("Enable"), ELEM_TYPE_INTEGER, default=1)
        card.optional_elem(
            n("Type"), ELEM_TYPE_ENUMERATED, items=biquad.TYPE_NAMES, default=default_type
        )
        card.optional_elem(
            n("Freq"),
            ELEM_TYPE_INTEGER,
            min_val=20 * FREQ_SCALE,
            max_val=20000 * FREQ_SCALE,
            default=1000 * FREQ_SCALE,
        )
        card.optional_elem(
            n("Q"),
            ELEM_TYPE_INTEGER,
            min_val=int(0.1 * Q_SCALE),
            max_val=10 * Q_SCALE,
            default=int(0.707 * Q_SCALE),
        )
        limit = int(GAIN_DB_LIMIT * GAIN_SCALE)
        card.optional_elem(n("Gain"), ELEM_TYPE_INTEGER, min_val=-limit, max_val=limit)


class Dsp:
    """The DSP of a card: its channels, which can be linked (then channel
    2 follows channel 1)."""

    @classmethod
    def for_card(cls, card: Card) -> Self | None:
        """The DSP of a card that has one."""
        if card.serial and card.elem("Line In 1 DSP Capture Switch"):
            return cls(card)
        return None

    def __init__(self, card: Card) -> None:
        self.card = card
        self.channels = [
            DspChannel(card, n) for n in (1, 2) if card.elem(f"Line In {n} DSP Capture Switch")
        ]
        for channel in self.channels:
            channel.create_elems()
        if len(self.channels) == 2:
            self._init_link()

    def channel(self, number: int) -> DspChannel | None:
        return next((c for c in self.channels if c.number == number), None)

    @property
    def link_elem(self) -> Elem | None:
        return self.card.elem(LINK_ELEM_NAME)

    def _pairs(self) -> list[tuple[Elem | None, Elem | None, bool]]:
        """(channel 1, channel 2, is_coeffs) of every linked value."""
        one, two = self.channels
        pairs = [
            (one.elem(name), two.elem(name), False)
            for name in ["DSP Capture Switch", *COMPRESSOR_PARAMS]
        ]
        for ls, rs in ((one.precomp_coeffs, two.precomp_coeffs), (one.peq_coeffs, two.peq_coeffs)):
            pairs += [(l, r, True) for l, r in zip(ls, rs)]
        return pairs

    def _sync_channels_on_link(self) -> None:
        """Copy all channel 1 values to channel 2."""
        for l, r, is_coeffs in self._pairs():
            if l and r:
                if is_coeffs:
                    r.set_int_values(l.get_int_values())
                else:
                    r.set_value(l.get_value())

    def _init_link(self) -> None:
        link = self.card.optional_elem(LINK_ELEM_NAME, ELEM_TYPE_BOOLEAN)

        was_linked = [bool(link.get_value())]

        def link_changed(e: Elem) -> None:
            linked = bool(e.get_value())
            if linked and not was_linked[0]:
                self._sync_channels_on_link()
            was_linked[0] = linked

        link.connect("changed", link_changed)

        # keep channel pairs in sync while linked
        def register_pair(l: Elem, r: Elem, is_coeffs: bool) -> None:
            def sync(elem: Elem) -> None:
                if not link.get_value():
                    return
                other = r if elem is l else l
                if is_coeffs:
                    values = elem.get_int_values()
                    if values != other.get_int_values():
                        other.set_int_values(values)
                else:
                    value = elem.get_value()
                    if value != other.get_value():
                        other.set_value(value)

            l.connect("changed", sync)
            r.connect("changed", sync)

        for l, r, is_coeffs in self._pairs():
            if l and r:
                register_pair(l, r, is_coeffs)

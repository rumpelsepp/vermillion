# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The base class of the supported interfaces.

Everything the driver's controls don't tell: the model by its USB
product ID, the names printed on the interface for its ports, which
digital inputs and outputs a digital I/O mode offers, and the special
cases of a model. Each product is a subclass (in the module of its
family) with an instance in vermilion.core.products.PRODUCTS.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from vermilion.core.constants import HW, PC, SR

# the ports with names of their own: (port category, hardware type,
# sink); the hardware type is only used for PC.HW
type PortKey = tuple[PC, HW, bool]

ANALOGUE_IN: PortKey = (PC.HW, HW.ANALOGUE, False)
ANALOGUE_OUT: PortKey = (PC.HW, HW.ANALOGUE, True)
MIX_OUT: PortKey = (PC.MIX, HW.ANALOGUE, False)
DSP_OUT: PortKey = (PC.DSP, HW.ANALOGUE, False)
# PCM outputs carry the audio from the computer, PCM inputs to it
PCM_OUT: PortKey = (PC.PCM, HW.ANALOGUE, False)
PCM_IN: PortKey = (PC.PCM, HW.ANALOGUE, True)

# stereo pair names of the analogue inputs, shared by many models
INST_12 = ("Mic/Line/Inst 1–2",)
INST_12_LINE_34 = ("Mic/Line/Inst 1–2", "Line 3–4")
INST_12_LINE_3456 = ("Mic/Line/Inst 1–2", "Line 3–4", "Line 5–6")
INST_12_LINE_345678 = ("Mic/Line/Inst 1–2", "Line 3–4", "Line 5–6", "Line 7–8")
INST_12_MIC_34_LINE_5678 = ("Mic/Line/Inst 1–2", "Mic/Line 3–4", "Line 5–6", "Line 7–8")
INST_12_MIC_345678 = ("Mic/Line/Inst 1–2", "Mic/Line 3–4", "Mic/Line 5–6", "Mic/Line 7–8")


def frozen[K, V](table: dict[K, V]) -> Mapping[K, V]:
    """A table of a product, read-only: the class attributes are shared."""
    return MappingProxyType(table)


# the number of channels at the low, mid and high sample rates
type Channels = tuple[int, int, int]


@dataclass(frozen=True)
class DigitalIo:
    """The digital inputs and outputs available in a digital I/O mode."""

    spdif_in: Channels
    spdif_out: Channels
    adat_in: Channels
    adat_out: Channels

    def at(self, sr_cat: SR) -> tuple[int, int, int, int]:
        """(S/PDIF in, out, ADAT in, out) at a sample rate category."""
        return (
            self.spdif_in[sr_cat],
            self.spdif_out[sr_cat],
            self.adat_in[sr_cat],
            self.adat_out[sr_cat],
        )


class Product:
    """A supported interface. Subclasses set the class attributes."""

    # USB product ID
    pid: ClassVar[int]
    # model name, as in the "Supported Hardware" dialog
    name: ClassVar[str]
    # product family, the groups of that dialog
    family: ClassVar[str]
    # the .state file in demo/ that simulates it (without the suffix)
    demo: ClassVar[str | None] = None

    # default names of ports and of stereo pairs (by pair index)
    port_names: ClassVar[Mapping[PortKey, Sequence[str]]] = {}
    pair_names: ClassVar[Mapping[PortKey, Sequence[str]]] = {}

    # the digital I/O by the item of the control that selects the mode
    # (None without that control); empty: all available
    digital_io: ClassVar[Mapping[str | None, DigitalIo]] = {}
    # the name of that control (up to the " Capture/Playback Enum")
    digital_io_control: ClassVar[str | None] = None
    # a new mode applies at once, not after a reboot of the interface
    digital_io_live: ClassVar[bool] = False
    # what the modes are (for the settings)
    digital_io_help: ClassVar[str | None] = None

    # special cases
    # the 1st Gen has its own kernel driver
    gen1: ClassVar[bool] = False
    # the master volume knob controls the line outputs 1 and 2 only
    # (instead of the outputs set to HW)
    knob_controls_line_12: ClassVar[bool] = False

    def port_name(self, category: int, hw_type: int, is_snk: bool, num: int) -> str | None:
        """Default name of a port (None if the model has none)."""
        return self._lookup(self.port_names, category, hw_type, is_snk, num)

    def pair_name(self, category: int, hw_type: int, is_snk: bool, pair: int) -> str | None:
        """Default name of a stereo pair (None if the model has none)."""
        return self._lookup(self.pair_names, category, hw_type, is_snk, pair)

    @staticmethod
    def _lookup(
        table: Mapping[PortKey, Sequence[str]], category: int, hw_type: int, is_snk: bool, i: int
    ) -> str | None:
        hw = HW(hw_type) if category == PC.HW else HW.ANALOGUE
        names = table.get((PC(category), hw, bool(is_snk)), ())
        return names[i] if 0 <= i < len(names) else None

    def io_limits(self, mode: str | None, sr_cat: SR) -> tuple[int, int, int, int] | None:
        """(max S/PDIF in, out, max ADAT in, out) in a digital I/O mode at
        a sample rate category; None if not known (all available)."""
        io = self.digital_io.get(mode)
        return io.at(sr_cat) if io else None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.pid:04x} {self.name}>"

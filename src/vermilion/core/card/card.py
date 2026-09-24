# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""A card: an interface with its elements, routing sources and sinks,
and the features of the application attached to it."""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar

from gi.repository import GLib, GObject

from vermilion.core.asound import (
    ELEM_TYPE_BYTES,
    ELEM_TYPE_ENUMERATED,
)
from vermilion.core.constants import (
    HW,
    MAX_MIX_OUT,
    MAX_MUX_IN,
    PC,
    PC_COUNT,
    SIMULATED_CARD_NUM,
    SR,
    Driver,
    SpeakerSwitch,
    get_sample_rate_category,
)
from vermilion.core.device.state import DeviceState
from vermilion.core.features.dsp import Dsp
from vermilion.core.features.mixer_mute import MixerMute
from vermilion.core.features.names import PortNames
from vermilion.core.features.sample_rate import SampleRateMonitor
from vermilion.core.features.stereo import StereoLinks
from vermilion.core.features.visibility import PortVisibility
from vermilion.core.ports import Port, RoutingSnk, RoutingSrc
from vermilion.core.products import Product, by_pid
from vermilion.core.signals import SignalSpec, signal
from vermilion.core.storage.config import Configuration
from vermilion.core.storage.prefs import Prefs
from vermilion.core.storage.presets import Presets
from vermilion.core.storage.state import SECTION_CONTROLS, CardState
from vermilion.core.util import get_num_from_string

if TYPE_CHECKING:
    from vermilion.core.features.levels import LevelMonitor

_log = logging.getLogger(__name__)


from vermilion.core.card.elem import Elem, SimElem


class Card(GObject.Object):
    """An interface: its elements, routing sources and sinks.

    Signals for the GUI (all emitted on the main loop):
    - removed
    - ui-update(flags: UiUpdate)
    - port-visibility-changed(port_category, is_src)
    - routing-changed, monitor-groups-state-changed, stereo-changed,
      mixer-widgets-changed, availability-changed, levels-changed
    - sample-rate-changed(rate, is_current)
    """

    __gsignals__: ClassVar[dict[str, SignalSpec]] = {
        "removed": signal(),
        "ui-update": signal(int),
        "port-visibility-changed": signal(int, bool),
        "routing-changed": signal(),
        "monitor-groups-state-changed": signal(),
        "stereo-changed": signal(),
        "mixer-widgets-changed": signal(),
        "availability-changed": signal(),
        "sample-rate-changed": signal(int, bool),
        "levels-changed": signal(),
    }

    def __init__(self, num: int) -> None:
        super().__init__()
        self.num = num
        self.device: str | None = None
        self.pid = 0
        self.serial: str | None = None
        self.name = ""
        self.driver_type = Driver.NONE

        self.elems: list[Elem] = []
        self._elems_by_name: dict[str, Elem] = {}

        self.sample_capture_elem: Elem | None = None
        self.level_meter_elem: Elem | None = None
        self.routing_srcs: list[RoutingSrc] = []
        self.routing_snks: list[RoutingSnk] = []
        self.monitor_group_src_map: list[int] = []
        self.routing_out_count = [0] * PC_COUNT
        self.routing_in_count = [0] * PC_COUNT
        self.mixer_gains: list[list[Elem | None]] = [
            [None] * MAX_MUX_IN for _ in range(MAX_MIX_OUT)
        ]

        self.has_speaker_switching = False
        self.has_talkback = False
        self.has_fixed_mixer_inputs = False
        self.mixer_has_mix_srcs = False
        self.has_levels = False

        # PCM channel availability based on sample rate
        self.playback_altset_channels = [0] * 4
        self.capture_altset_channels = [0] * 4
        self.altset_count = 0
        self.pcm_playback_channels = 0
        self.pcm_capture_channels = 0

        # HW I/O availability based on digital I/O mode and sample rate
        self.digital_io_mode_elem: Elem | None = None
        self.digital_io_mode = 0
        self.current_sample_rate = 0
        self.max_spdif_in = -1
        self.max_spdif_out = -1
        self.max_adat_in = -1
        self.max_adat_out = -1

        # level meters (dB), updated by LevelMonitor
        self.routing_levels: list[float] = []

        # its files: state, preferences, presets
        self.state = CardState(self)
        self.prefs = Prefs(self)
        self.presets = Presets(self)
        self.config = Configuration(self)
        # the saved values of the simulated controls (see optional_elem)
        self._saved_controls: dict[str, str] | None = None

        # monitors and cleanup hooks
        self.levels: LevelMonitor | None = None
        self.names: PortNames | None = None
        self.visibility: PortVisibility | None = None
        self.stereo: StereoLinks | None = None
        self.mixer_mute: MixerMute | None = None
        self.device_state: DeviceState | None = None
        self.dsp: Dsp | None = None
        self.sample_rate: SampleRateMonitor | None = None
        self._ui_update_flags = 0
        self._ui_update_idle = 0
        self._cleanups: list[Callable[[], object]] = []

    def __repr__(self) -> str:
        return f"<Card {self.num} {self.name!r}>"

    @property
    def product(self) -> Product | None:
        """The supported product, by the USB product ID (None if unknown)."""
        return by_pid(self.pid)

    @property
    def is_simulated(self) -> bool:
        return self.num == SIMULATED_CARD_NUM

    @property
    def is_open(self) -> bool:
        """Are the elements still there (not for a removed card)?"""
        return True

    # element lookup

    def add_elem(self, elem: Elem) -> Elem:
        self.elems.append(elem)
        self._elems_by_name.setdefault(elem.name, elem)
        return elem

    def elem(self, name: str) -> Elem | None:
        """Element with exactly this name (first one), or None."""
        return self._elems_by_name.get(name)

    def first_elem(self, *names: str) -> Elem | None:
        """The first element of names that exists."""
        return next((e for name in names if (e := self.elem(name))), None)

    def elem_by_prefix(self, prefix: str) -> Elem | None:
        for e in self.elems:
            if e.name.startswith(prefix):
                return e
        return None

    def elem_by_substr(self, substr: str) -> Elem | None:
        for e in self.elems:
            if substr in e.name:
                return e
        return None

    def max_elem_num(self, prefix: str, needle: str) -> int:
        """Highest number in names matching prefix and containing needle.

        e.g. max_elem_num("Line", "Pad Capture Switch") returns 8 when the
        last matching control is "Line In 8 Pad Capture Switch".
        """
        best = 0
        for e in self.elems:
            if e.name.startswith(prefix) and needle in e.name:
                best = max(best, get_num_from_string(e.name))
        return best

    def optional_elem(
        self,
        name: str,
        elem_type: int,
        *,
        default: int = 0,
        max_val: int = 1,
        min_val: int = 0,
        items: list[str] | None = None,
        size: int = 32,
    ) -> Elem:
        """The control name: the driver's if it has one, else a simulated
        one (for a control the application adds) whose value is kept in
        the state file.

        Booleans are kept as "1"/"0", integers and enum items as numbers,
        bytes as text. Integers are between min_val and max_val, enums
        have items, bytes up to size bytes; default is the value of a new
        boolean, integer or enum.
        """
        elem = self.elem(name)
        if elem:
            return elem
        elem = SimElem(self, 0, name, elem_type)
        elem.optional = True
        elem.is_writable = True
        if elem_type == ELEM_TYPE_ENUMERATED:
            elem.item_names = list(items or [])
            min_val, max_val = 0, len(elem.item_names) - 1
        elem.min_val, elem.max_val = min_val, max_val
        if self._saved_controls is None:
            self._saved_controls = self.state.load(SECTION_CONTROLS)
        saved = self._saved_controls.get(name)

        if elem_type == ELEM_TYPE_BYTES:
            elem.bytes_size = size
            elem.bytes_value = (saved or "").encode()[:size]
            elem.count = len(elem.bytes_value)
        else:
            value = default
            if saved:
                try:
                    value = max(min_val, min(max_val, int(saved)))
                except ValueError:
                    pass
            elem.value = value

        def save(e: Elem) -> None:
            if e.type == ELEM_TYPE_BYTES:
                self.state.save(SECTION_CONTROLS, name, e.get_str())
            else:
                self.state.save(SECTION_CONTROLS, name, str(e.get_value()))

        elem.connect("changed", save)
        return self.add_elem(elem)

    # routing helpers

    @property
    def ports(self) -> list[Port]:
        """All routing sources and sinks."""
        return [*self.routing_srcs, *self.routing_snks]

    def src(self, idx: int) -> RoutingSrc | None:
        if 0 <= idx < len(self.routing_srcs):
            return self.routing_srcs[idx]
        return None

    def srcs_of(self, port_category: int) -> list[RoutingSrc]:
        return [s for s in self.routing_srcs if s.port_category == port_category]

    def snks_of(self, port_category: int) -> list[RoutingSnk]:
        return [s for s in self.routing_snks if s.elem.port_category == port_category]

    def mixer_src(self, mix_num: int) -> RoutingSrc | None:
        for s in self.routing_srcs:
            if s.port_category == PC.MIX and s.port_num == mix_num:
                return s
        return None

    def mixer_snk(self, input_num: int) -> RoutingSnk | None:
        """Mixer input sink by 1-based number."""
        for s in self.routing_snks:
            if s.elem.port_category == PC.MIX and s.elem.lr_num == input_num:
                return s
        return None

    def analogue_output_snk(self, lr_num: int) -> RoutingSnk | None:
        for s in self.routing_snks:
            e = s.elem
            if e.port_category == PC.HW and e.hw_type == HW.ANALOGUE and e.lr_num == lr_num:
                return s
        return None

    def mixer_gain_min_val(self) -> int:
        e = self.mixer_gains[0][0]
        return e.min_val if e else 0

    def level_db(self, index: int) -> float:
        if 0 <= index < len(self.routing_levels):
            return self.routing_levels[index]
        return -80.0

    def src_level_db(self, src: RoutingSrc) -> float:
        """Level in dB for a routing source (-80 if no level data)."""
        if src.level_index < 0:
            return -80.0
        return self.level_db(src.level_index)

    # UI update scheduling

    # building the model from the elements

    def setup(self) -> None:
        """Build the model once all elements exist (real and simulated),
        with the features of the application (names, stereo links, ...)."""
        self._set_lr_nums()
        self._find_routing_controls()
        self._cache_mixer_gains()

        self.has_speaker_switching = bool(
            self.elem("Speaker Switching Playback Enum")
            or self.elem("Speaker Switching Playback Switch")
        )
        self.has_talkback = bool(
            self.elem("Talkback Playback Enum") or self.elem("Talkback Enable Playback Switch")
        )
        self.has_levels = self.elem("Firmware Version") is not None

        # per-mix talkback switches ("Talkback Mix A Playback Switch", ...)
        if self.has_talkback:
            for src in self.srcs_of(PC.MIX):
                letter = chr(ord("A") + src.lr_num - 1)
                src.talkback_elem = self.elem(f"Talkback Mix {letter} Playback Switch")

        # the features, in this order: names and visibility of the ports,
        # which stereo links need, which mute and solo need
        self.prefs.load()
        self.names = PortNames(self)
        self.visibility = PortVisibility(self)
        self.stereo = StereoLinks(self)
        self.mixer_mute = MixerMute.for_card(self)
        self.device_state = DeviceState.for_card(self)
        self.dsp = Dsp.for_card(self)
        self._watch_routing()
        self.sample_rate = SampleRateMonitor(self)

    def _set_lr_nums(self) -> None:
        for elem in self.elems:
            elem.parse_lr_num()

    def _find_routing_controls(self) -> None:

        self.sample_capture_elem = (
            self.elem("PCM 01 Capture Enum")
            or self.elem("PCM 1 Capture Enum")
            or self.elem("Input Source 01 Capture Route")
        )

        if not self.sample_capture_elem:
            _log.warning(
                "can't find routing control PCM 01 Capture Enum or Input Source 01 Capture Route"
            )
            return

        self._find_routing_srcs()
        self._find_routing_snks()
        self._map_monitor_group_srcs()

        # look up the Digital I/O Mode element for HW I/O availability
        product = self.product
        if product and product.digital_io_control:
            self.digital_io_mode_elem = self.elem_by_prefix(product.digital_io_control)

        # cache the mode value at init time
        if self.digital_io_mode_elem:
            self.digital_io_mode = self.digital_io_mode_elem.get_value()

        self.update_io_limits()

    def _find_routing_srcs(self) -> None:
        elem = self.sample_capture_elem
        assert elem is not None
        self.routing_srcs = []

        for i, name in enumerate(elem.items()):
            r = RoutingSrc(self, i, name)

            if name == "Off":
                r.port_category = PC.OFF
            elif name.startswith("Mix"):
                r.port_category = PC.MIX
            elif name.startswith("DSP"):
                r.port_category = PC.DSP
            elif name.startswith("PCM"):
                r.port_category = PC.PCM
            else:
                r.port_category = PC.HW
                if name.startswith("Analog"):
                    r.hw_type = HW.ANALOGUE
                elif name.startswith(("S/PDIF", "SPDIF")):
                    r.hw_type = HW.SPDIF
                elif name.startswith("ADAT"):
                    r.hw_type = HW.ADAT

            if r.port_category == PC.MIX:
                r.lr_num = ord(name[4]) - ord("A") + 1 if len(name) > 4 else 0
            else:
                r.lr_num = get_num_from_string(name)
            # odd channels (A, C, ... for mixer outputs) are left
            r.is_left = r.lr_num % 2 == 1

            r.port_num = self.routing_in_count[r.port_category]
            self.routing_in_count[r.port_category] += 1
            self.routing_srcs.append(r)

        assert self.routing_in_count[PC.MIX] <= MAX_MIX_OUT

    @staticmethod
    def _is_routing_snk(name: str) -> bool:
        if (
            "Capture Route" in name
            or "Input Playback Route" in name
            or (name.startswith("Master ") and "Source Playback Enu" in name)
        ):
            return True

        if "Capture Enum" in name and name.startswith(("PCM ", "Mixer ", "DSP ")):
            return True

        return bool("Playback Enum" in name and name.startswith(("Analogue ", "S/PDIF ", "ADAT ")))

    def _find_routing_snks(self) -> None:
        first_mix_snk = None
        snk_elems = []

        for elem in self.elems:
            if not self._is_routing_snk(elem.name):
                continue

            name = elem.name

            if name.startswith(("Mixer", "Matrix")):
                elem.port_category = PC.MIX
                if first_mix_snk is None:
                    first_mix_snk = elem
            elif name.startswith("DSP"):
                elem.port_category = PC.DSP
            elif name.startswith(("PCM", "Input Source")):
                elem.port_category = PC.PCM
            elif "Playback Enu" in name:
                elem.port_category = PC.HW
                if name.startswith("Analog"):
                    elem.hw_type = HW.ANALOGUE
                elif name.startswith("S/PDIF") or "SPDIF" in name:
                    elem.hw_type = HW.SPDIF
                elif "ADAT" in name:
                    elem.hw_type = HW.ADAT
            else:
                _log.warning(f"unknown mixer routing elem {name}")
                continue

            if elem.lr_num <= 0:
                _log.warning(f"routing sink {name} had no number")
                continue

            snk_elems.append(elem)

        # check mixer input capabilities from the first PC_MIX sink
        if first_mix_snk:
            if not first_mix_snk.writable():
                self.has_fixed_mixer_inputs = True
            self.mixer_has_mix_srcs = any(item.startswith("Mix") for item in first_mix_snk.items())

        self.routing_snks = []
        for j, elem in enumerate(snk_elems):
            r = RoutingSnk(j, elem)
            elem.port_num = self.routing_out_count[elem.port_category]
            self.routing_out_count[elem.port_category] += 1

            # cache monitor group element pointers for HW analogue outputs
            if elem.port_category == PC.HW and elem.hw_type == HW.ANALOGUE:
                n = elem.lr_num
                r.main_group_switch = self.elem(f"Main Group Output {n} Playback Switch")
                r.alt_group_switch = self.elem(f"Alt Group Output {n} Playback Switch")
                r.main_group_source = self.elem(f"Main Group Output {n} Source Playback Enum")
                r.alt_group_source = self.elem(f"Alt Group Output {n} Source Playback Enum")
                r.main_group_trim = self.elem(f"Main Group Output {n} Trim Playback Volume")
                r.alt_group_trim = self.elem(f"Alt Group Output {n} Trim Playback Volume")

            r.effective_source_idx = elem.get_value()

            # For fixed mixer inputs, use the source's left/right (lr_num can
            # be misaligned on devices with odd analogue input count)
            if elem.port_category == PC.MIX and not elem.writable():
                src = self.src(r.effective_source_idx)
                if src and src.id > 0:
                    r.is_left = src.lr_num % 2 == 1
                else:
                    r.is_left = elem.lr_num % 2 == 1
            else:
                r.is_left = elem.lr_num % 2 == 1

            self.routing_snks.append(r)

        assert self.routing_out_count[PC.MIX] <= MAX_MUX_IN

    def _map_monitor_group_srcs(self) -> None:
        """Map monitor group source enum values to routing source indices."""
        vg_elem = self.elem("Main Group Output 1 Source Playback Enum")
        self.monitor_group_src_map = []
        if not vg_elem:
            return

        by_name: dict[str, int] = {}
        for j, src in enumerate(self.routing_srcs):
            by_name.setdefault(src.name, j)

        self.monitor_group_src_map = [by_name.get(name, 0) for name in vg_elem.items()]

    def _cache_mixer_gains(self) -> None:
        for elem in self.elems:
            name = elem.name
            if "Playback Volume" not in name:
                continue

            # Gen 2+: "Mix X Input Y", Gen 1: "Matrix Y Mix X"
            if not name.startswith("Mix ") and not name.startswith("Matrix "):
                continue

            pos = name.find("Mix ")
            if pos < 0 or len(name) <= pos + 4:
                continue

            mix_num = ord(name[pos + 4]) - ord("A")
            input_num = get_num_from_string(name) - 1

            if not 0 <= mix_num < MAX_MIX_OUT or not 0 <= input_num < MAX_MUX_IN:
                continue

            self.mixer_gains[mix_num][input_num] = elem

    # driver and firmware

    @property
    def driver_description(self) -> str:
        if self.is_simulated:
            return "none (simulated)"
        if self.driver_type == Driver.FCP:
            return "FCP (not supported yet)"
        if self.product and self.product.gen1:
            return "Scarlett Gen 1 mixer driver"
        if self.driver_type == Driver.HWDEP:
            return "Scarlett2 mixer driver"
        return "Scarlett2 mixer driver (without hwdep: no reset of the configuration)"

    @property
    def firmware_version(self) -> int | None:
        elem = self.elem("Firmware Version")
        return elem.get_value() if elem else None

    @property
    def required_firmware_version(self) -> int:
        """The firmware version the driver needs (0 if not known)."""
        elem = self.elem("Minimum Firmware Version")
        return elem.get_value() if elem else 0

    @property
    def firmware_too_old(self) -> bool:
        """Is the firmware older than the driver requires?"""
        version = self.firmware_version
        return version is not None and version < self.required_firmware_version

    # names

    @property
    def name_elem(self) -> Elem | None:
        """The name given to the interface (a real or optional control)."""
        return self.elem("Name")

    @property
    def custom_name(self) -> str:
        elem = self.name_elem
        return elem.get_str() if elem else ""

    @property
    def title_parts(self) -> tuple[str, str]:
        """Title and subtitle: the custom name and the model, or the model
        and the serial number."""
        if self.custom_name:
            return self.custom_name, self.name
        serial = self.serial if self.serial != self.name else ""
        return self.name, serial or ""

    @property
    def window_title(self) -> str:
        """The model plus the custom name or the serial number."""
        extra = self.custom_name or self.serial
        return f"{self.name} - {extra}" if extra else self.name

    # routing

    def update_effective_sources(self) -> None:
        for snk in self.routing_snks:
            snk.update_effective_source()

    def _watch_routing(self) -> None:
        """Keep effective sources up to date and notify the GUI."""

        if not self.routing_snks:
            return

        def snk_changed(snk: RoutingSnk) -> None:
            snk.update_effective_source()
            self.emit("routing-changed")

        for snk in self.routing_snks:
            snk.elem.connect("changed", lambda _e, snk=snk: snk_changed(snk))

        def monitor_group_changed(_elem: Elem) -> None:
            self.update_effective_sources()
            self.emit("monitor-groups-state-changed")
            self.emit("routing-changed")

        names = [
            "Speaker Switching Playback Enum",
            "Speaker Switching Playback Switch",
            "Speaker Switching Alt Playback Switch",
        ]
        for i in range(1, 9):
            for group in ("Main", "Alt"):
                names.append(f"{group} Group Output {i} Playback Switch")
                names.append(f"{group} Group Output {i} Source Playback Enum")
        for name in names:
            elem = self.elem(name)
            if elem:
                elem.connect("changed", monitor_group_changed)

        if self.digital_io_mode_elem:

            def digital_io_mode_changed(_elem: Elem) -> None:
                self.update_io_limits()
                self.emit("availability-changed")

            self.digital_io_mode_elem.connect("changed", digital_io_mode_changed)

        self.update_effective_sources()

    def _preset_link(self, src_pc: int, src_mod: int, snk_pc: int) -> None:
        srcs = [s for s in self.routing_srcs[1:] if s.port_category == src_pc]
        snks = [s for s in self.routing_snks if s.elem.port_category == snk_pc]
        if not srcs:
            return
        # the C implementation assigns in order, cycling through the sources
        # every src_mod entries (0 = never)
        first = self.routing_srcs.index(srcs[0])
        src_idx = first
        count = 0
        for snk in snks:
            if src_idx >= len(self.routing_srcs):
                break
            src = self.routing_srcs[src_idx]
            if src.port_category != src_pc:
                break
            snk.elem.set_value(src.id)
            src_idx += 1
            count += 1
            if count == src_mod:
                src_idx = first
                count = 0

    def apply_routing_preset(self, name: str) -> None:
        """ "clear", "direct", "preamp" or "stereo_out"."""
        if name == "clear":
            for snk in self.routing_snks:
                snk.elem.set_value(0)
        elif name == "direct":
            self._preset_link(PC.HW, 0, PC.PCM)
            self._preset_link(PC.PCM, 0, PC.HW)
        elif name == "preamp":
            self._preset_link(PC.HW, 0, PC.HW)
        elif name == "stereo_out":
            self._preset_link(PC.PCM, 2, PC.HW)

    # digital I/O availability

    def update_io_limits(self) -> None:
        """max_{spdif,adat}_{in,out} by the digital I/O mode and the
        sample rate; -1 means unknown/all."""
        mode = None
        elem = self.digital_io_mode_elem
        if elem:
            live = bool(self.product and self.product.digital_io_live)
            value = elem.get_value() if live else self.digital_io_mode
            mode = elem.item_name(value)

        sr_cat = get_sample_rate_category(self.current_sample_rate)
        limits = self.product.io_limits(mode, sr_cat) if self.product else None
        if limits:
            self.max_spdif_in, self.max_spdif_out, self.max_adat_in, self.max_adat_out = limits
            return
        self.max_spdif_in = self.max_spdif_out = -1
        self.max_adat_in = self.max_adat_out = -1

        # no warning for simulated devices or devices without a mode
        if mode and not self.is_simulated:
            _log.warning(
                "unknown digital I/O config: pid=0x%04x mode=%s sr_cat=%d", self.pid, mode, sr_cat
            )

    # speaker switching and monitor groups

    def _any_group_enabled(self, group: str) -> bool:
        for i in range(1, 9):
            elem = self.elem(f"{group} Group Output {i} Playback Switch")
            if elem and elem.get_value():
                return True
        return False

    @property
    def has_alt_group(self) -> bool:
        """Is any output in the Alt monitor group?"""
        return self._any_group_enabled("Alt")

    @property
    def speaker_switching(self) -> SpeakerSwitch:
        # enum version (Gen 2/3 larger models): 0=Off, 1=Main, 2=Alt
        elem = self.elem("Speaker Switching Playback Enum")
        if elem:
            val = elem.get_value()
            if val == 0:
                return SpeakerSwitch.OFF
            return SpeakerSwitch.ALT if val == 2 else SpeakerSwitch.MAIN

        # Main/Alt Group controls (Gen 4)
        if self.elem_by_prefix("Main Group Output"):
            if self.has_alt_group:
                alt = self.elem("Speaker Switching Alt Playback Switch")
                if alt and alt.get_value():
                    return SpeakerSwitch.ALT
                return SpeakerSwitch.MAIN
            if self._any_group_enabled("Main"):
                return SpeakerSwitch.MAIN
            return SpeakerSwitch.OFF

        # switch version (Gen 2/3 smaller models)
        sw = self.elem("Speaker Switching Playback Switch")
        alt = self.elem("Speaker Switching Alt Playback Switch")
        if sw and alt:
            if not sw.get_value():
                return SpeakerSwitch.OFF
            return SpeakerSwitch.ALT if alt.get_value() else SpeakerSwitch.MAIN

        return SpeakerSwitch.OFF

    def monitor_group_index(self, src_id: int) -> int:
        """The monitor group source enum value of a routing source."""
        try:
            return self.monitor_group_src_map.index(src_id)
        except ValueError:
            return 0

    @property
    def mixer_available(self) -> bool:
        """The mixer is off at the highest sample rates."""
        return get_sample_rate_category(self.current_sample_rate) != SR.HIGH

    def schedule_ui_update(self, flags: int) -> None:
        """Coalesce expensive UI rebuilds into one idle callback."""
        self._ui_update_flags |= flags
        if not self._ui_update_idle:
            self._ui_update_idle = GLib.idle_add(
                self._flush_ui_update, priority=GLib.PRIORITY_HIGH_IDLE
            )

    def _flush_ui_update(self) -> bool:
        self._ui_update_idle = 0
        flags = self._ui_update_flags
        self._ui_update_flags = 0
        self.emit("ui-update", flags)
        return GLib.SOURCE_REMOVE

    # lifecycle

    def on_destroy(self, fn: Callable[[], object]) -> None:
        self._cleanups.append(fn)

    def destroy(self) -> None:
        for fn in self._cleanups:
            fn()
        self._cleanups = []
        if self._ui_update_idle:
            GLib.source_remove(self._ui_update_idle)
            self._ui_update_idle = 0
        for e in self.elems:
            e.cancel_idle()
        self.emit("removed")

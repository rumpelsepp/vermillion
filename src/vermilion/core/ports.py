# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Routing ports: sources (items of the routing enums, e.g. "Analogue 1")
and sinks (the elements choosing a source, e.g. "PCM 01 Capture Enum").

Both have a category (hardware, mixer, DSP, PCM), a channel number and
optional elements for a custom name, visibility and stereo linking with
the neighbouring channel. Port holds everything they share; sources and
sinks differ in where their data comes from and in a few names.
"""

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, ClassVar, Self

from gi.repository import GObject

from vermilion.core.constants import (
    HW,
    HW_TYPE_NAMES,
    PC,
    UNAVAILABLE_DIGITAL,
    UNAVAILABLE_MIXER,
    UNAVAILABLE_SAMPLE_RATE,
    SpeakerSwitch,
    is_digital_io_type,
)
from vermilion.core.signals import SignalSpec, signal

if TYPE_CHECKING:
    from vermilion.core.card import Card, Elem

_log = logging.getLogger(__name__)

EN_DASH = "–"


class Port(GObject.Object):
    """A routing source or sink.

    Emits "name-changed" when the display name changes.
    """

    __gsignals__: ClassVar[dict[str, SignalSpec]] = {"name-changed": signal()}

    # sources are "In" for hardware and "Out" otherwise, sinks the reverse
    is_src: ClassVar[bool]

    def __init__(self, card: Card) -> None:
        super().__init__()
        self.card = card
        self.custom_name_elem: Elem | None = None
        self.enable_elem: Elem | None = None
        # stereo pair: the link and name elements are on the left port
        self.link_elem: Elem | None = None
        self.pair_name_elem: Elem | None = None
        self.is_left = False
        self._partner: Port | None = None
        # mixer inputs and outputs: mute and solo switches (see mixer_mute)
        self.mute_elem: Elem | None = None
        self.solo_elem: Elem | None = None
        self.display_name = ""
        self.level_index = -1

    # the name, category and numbering: stored by sources, taken from the
    # element by sinks

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def port_category(self) -> PC:
        raise NotImplementedError

    @property
    def hw_type(self) -> HW:
        raise NotImplementedError

    @property
    def port_num(self) -> int:
        """Index within the category."""
        raise NotImplementedError

    @property
    def lr_num(self) -> int:
        """1-based channel number."""
        raise NotImplementedError

    @property
    def mixer_index(self) -> int:
        """Row (output) or column (input) of a mixer port in the gain
        matrix."""
        raise NotImplementedError

    def _siblings(self) -> Sequence[Port]:
        """All ports of the same kind (sources or sinks) of the card."""
        raise NotImplementedError

    # stereo pairs

    @property
    def partner(self) -> Self | None:
        """The other channel of a potential stereo pair."""
        if isinstance(self._partner, type(self)):
            return self._partner
        partner_lr = self.lr_num + 1 if self.is_left else self.lr_num - 1
        for other in self._siblings():
            if not isinstance(other, type(self)) or other.port_category != self.port_category:
                continue
            if self.port_category == PC.HW and other.hw_type != self.hw_type:
                continue
            if other.lr_num != partner_lr:
                continue
            # the match must be the opposite channel
            if other.is_left == self.is_left:
                return None
            self._partner, other._partner = other, self
            return other
        return None

    @property
    def left(self) -> Self | None:
        """The left port of the pair (self if it is the left one)."""
        return self if self.is_left else self.partner

    @property
    def stereo_link_elem(self) -> Elem | None:
        left = self.left
        return left.link_elem if left else None

    @property
    def stereo_name_elem(self) -> Elem | None:
        left = self.left
        return left.pair_name_elem if left else None

    @property
    def is_linked(self) -> bool:
        link = self.stereo_link_elem
        return bool(link and link.get_value())

    @property
    def should_display(self) -> bool:
        """False for the right channel of a linked pair."""
        return not self.is_linked or self.is_left

    @property
    def enabled(self) -> bool:
        return not self.enable_elem or bool(self.enable_elem.get_value())

    @property
    def visible(self) -> bool:
        return self.enabled and self.should_display

    # names

    def _mix_label(self) -> str:
        """Short name of a mixer port ("A" or "3")."""
        raise NotImplementedError

    def _mix_pair_label(self) -> str:
        """Short name of a mixer port pair ("A–B" or "3–4")."""
        raise NotImplementedError

    _mix_prefix: ClassVar[str]

    def control_name(self, suffix: str, stereo: bool = False) -> str | None:
        """Name of an element for this port or pair, e.g. "PCM In 1 Name"
        or "Analogue Out 1-2 Link"; None for "Off"."""
        prefix = {
            PC.PCM: "PCM",
            PC.MIX: "Mixer",
            PC.DSP: "DSP",
        }.get(self.port_category)
        if self.port_category == PC.HW:
            prefix = HW_TYPE_NAMES[self.hw_type]
        if prefix is None:
            return None
        direction = "In" if (self.port_category == PC.HW) == self.is_src else "Out"
        number = f"{self.lr_num}-{self.lr_num + 1}" if stereo else str(self.lr_num)
        return f"{prefix} {direction} {number} {suffix}"

    def _category_name(self, number: str, mix_label: str) -> str:
        pc = self.port_category
        if pc == PC.HW:
            return f"{HW_TYPE_NAMES[self.hw_type]} {number}"
        if pc == PC.PCM:
            return f"PCM {number}"
        if pc == PC.MIX:
            return f"{self._mix_prefix} {mix_label}"
        if pc == PC.DSP:
            return f"DSP {number}"
        return ""

    @property
    def generic_name(self) -> str:
        """ "Analogue 1", "Mix A", "Mixer 3", ..."""
        return self._category_name(str(self.lr_num), self._mix_label()) or self.name

    @property
    def generic_pair_name(self) -> str:
        n = self.lr_num
        return self._category_name(f"{n}{EN_DASH}{n + 1}", self._mix_pair_label())

    @property
    def device_name(self) -> str | None:
        """Product-specific default name (e.g. "Mic 1"), if any."""
        product = self.card.product
        if not product:
            return None
        return product.port_name(self.port_category, self.hw_type, not self.is_src, self.port_num)

    @property
    def device_pair_name(self) -> str | None:
        product = self.card.product
        if not product:
            return None
        pair = (self.lr_num - 1) // 2
        return product.pair_name(self.port_category, self.hw_type, not self.is_src, pair)

    def default_name(self, abbreviated: bool = False) -> str:
        """Name ignoring the custom name; mixer and DSP ports in the short
        form ("A", "1") of the routing window if abbreviated."""
        if abbreviated and self.port_category == PC.MIX:
            return self._mix_label()
        if abbreviated and self.port_category == PC.DSP:
            return str(self.lr_num)
        return self.device_name or self.generic_name

    @property
    def default_pair_name(self) -> str:
        return self.device_pair_name or self.generic_pair_name

    @property
    def display_name_formatted(self) -> str:
        """Name shown for the port; mixer and DSP ports abbreviated."""
        if self.port_category in (PC.MIX, PC.DSP):
            return self.default_name(True)
        return self.display_name

    @property
    def stereo_aware_name(self) -> str:
        """Name in the routing window: the pair name for a linked pair."""
        if not (self.is_linked and self.is_left):
            return self.display_name_formatted
        if self.port_category == PC.MIX:
            return self._mix_pair_label()
        if self.port_category == PC.DSP:
            return f"{self.lr_num}{EN_DASH}{self.lr_num + 1}"
        return self.pair_display_name

    @property
    def pair_display_name(self) -> str:
        """Custom or default name of the stereo pair."""
        left = self.left
        if not left:
            return ""
        custom = left.pair_name_elem.get_str() if left.pair_name_elem else ""
        return custom or left.default_pair_name

    def update_display_name(self) -> None:
        custom = self.custom_name_elem.get_str() if self.custom_name_elem else ""
        self.display_name = custom or self.default_name()

    # availability

    def availability(self) -> tuple[bool, str | None]:
        """(available, tooltip): by sample rate and digital I/O mode."""
        card = self.card
        pc = self.port_category
        if pc == PC.MIX or (pc == PC.DSP and not self.is_src):
            return card.mixer_available, UNAVAILABLE_MIXER
        if pc == PC.HW and is_digital_io_type(self.hw_type):
            spdif = self.hw_type == HW.SPDIF
            if self.is_src:
                max_port = card.max_spdif_in if spdif else card.max_adat_in
            else:
                max_port = card.max_spdif_out if spdif else card.max_adat_out
            return max_port < 0 or self.lr_num <= max_port, UNAVAILABLE_DIGITAL
        if pc == PC.PCM:
            channels = card.pcm_playback_channels if self.is_src else card.pcm_capture_channels
            return channels == 0 or self.port_num < channels, UNAVAILABLE_SAMPLE_RATE
        return True, None


class RoutingSrc(Port):
    """A routing source: an item of the routing enums (e.g. "Analogue 1")."""

    is_src = True
    _mix_prefix = "Mix"

    # plain attributes instead of the properties of Port
    name: str = ""
    port_category: PC = PC.OFF
    hw_type: HW = HW.ANALOGUE
    port_num: int = 0
    lr_num: int = 0

    def __init__(self, card: Card, src_id: int, name: str) -> None:
        super().__init__(card)
        self.id = src_id
        self.name = name
        self.talkback_elem: Elem | None = None

    def __repr__(self) -> str:
        return f"<RoutingSrc {self.id} {self.name!r}>"

    def _siblings(self) -> Sequence[Port]:
        return self.card.routing_srcs

    @property
    def mixer_index(self) -> int:
        return self.port_num

    def _mix_label(self) -> str:
        return chr(self.port_num + ord("A"))

    def _mix_pair_label(self) -> str:
        return f"{self._mix_label()}{EN_DASH}{chr(self.port_num + ord('B'))}"

    def disconnect_sinks(self) -> None:
        """Clear all sinks connected to this source (or its linked
        partner)."""
        partner = self.partner if self.is_linked else None
        for snk in self.card.routing_snks:
            idx = snk.effective_source_idx
            if idx != self.id and not (partner and idx == partner.id):
                continue
            target = snk.routing_elem
            if target is not None and target is snk.elem:
                target.set_value(0)

    @property
    def talkback_label(self) -> str:
        """Stereo-aware talkback button label ("A" or "A–B")."""
        return self._mix_pair_label() if self.is_linked and self.is_left else self._mix_label()

    @property
    def mixer_label(self) -> str:
        """Label of a mixer output in the mixer window."""
        if self.port_category != PC.MIX:
            return ""
        return self.display_name or self.default_name()


class RoutingSnk(Port):
    """A routing sink: an element choosing its source (e.g. "PCM 01 Capture
    Enum"); the category and numbering are those of the element."""

    is_src = False
    _mix_prefix = "Mixer"

    def __init__(self, idx: int, elem: Elem) -> None:
        super().__init__(elem.card)
        self.idx = idx
        self.elem = elem
        self.effective_source_idx = 0

        self.main_group_switch: Elem | None = None
        self.alt_group_switch: Elem | None = None
        self.main_group_source: Elem | None = None
        self.alt_group_source: Elem | None = None
        self.main_group_trim: Elem | None = None
        self.alt_group_trim: Elem | None = None

    def __repr__(self) -> str:
        return f"<RoutingSnk {self.idx} {self.elem.name!r}>"

    def _siblings(self) -> Sequence[Port]:
        return self.card.routing_snks

    @property
    def mixer_index(self) -> int:
        return self.lr_num - 1

    # delegated to the element

    @property
    def name(self) -> str:
        return self.elem.name

    @property
    def port_category(self) -> PC:
        return self.elem.port_category

    @property
    def hw_type(self) -> HW:
        return self.elem.hw_type

    @property
    def port_num(self) -> int:
        return self.elem.port_num

    @property
    def lr_num(self) -> int:
        return self.elem.lr_num

    def _mix_label(self) -> str:
        return str(self.lr_num)

    def _mix_pair_label(self) -> str:
        return f"{self.lr_num}{EN_DASH}{self.lr_num + 1}"

    # monitor groups (hardware analogue outputs of the 4th Gen)

    def _group_membership(self) -> tuple[bool, bool] | None:
        """(in_main, in_alt) or None if not affected by monitor groups."""
        e = self.elem
        if e.port_category != PC.HW or e.hw_type != HW.ANALOGUE:
            return None
        if not self.main_group_switch and not self.alt_group_switch:
            return None
        in_main = bool(self.main_group_switch and self.main_group_switch.get_value())
        in_alt = bool(self.alt_group_switch and self.alt_group_switch.get_value())
        if not in_main and not in_alt:
            return None
        return in_main, in_alt

    @property
    def monitor_muted(self) -> bool:
        """Muted because it's only in the inactive monitor group?"""
        m = self._group_membership()
        if not m:
            return False
        in_main, in_alt = m
        if self.card.speaker_switching in (SpeakerSwitch.OFF, SpeakerSwitch.MAIN):
            return in_alt and not in_main
        return in_main and not in_alt

    @property
    def routing_elem(self) -> Elem | None:
        """The element to change to route to this sink.

        The group source element if the sink is in the active monitor
        group, otherwise the routing element; None if the sink is muted.
        """
        m = self._group_membership()
        if not m:
            return self.elem
        in_main, in_alt = m
        if self.card.speaker_switching in (SpeakerSwitch.OFF, SpeakerSwitch.MAIN):
            return self.main_group_source if in_main else None
        return self.alt_group_source if in_alt else None

    def route_from(self, src_id: int) -> None:
        """Connect the source src_id (0: none) to this sink."""
        target = self.routing_elem
        if not target:
            return
        if target is not self.elem:
            src_id = self.card.monitor_group_index(src_id)
        target.set_value(src_id)

    def update_effective_source(self) -> None:
        """The source actually heard (via the active monitor group)."""
        card = self.card
        m = self._group_membership()
        if not m:
            self.effective_source_idx = self.elem.get_value()
            return

        in_main, in_alt = m
        mg_map = card.monitor_group_src_map
        state = card.speaker_switching

        if state in (SpeakerSwitch.OFF, SpeakerSwitch.MAIN):
            if in_main and self.main_group_source:
                vg = self.main_group_source.get_value()
                if vg < len(mg_map):
                    self.effective_source_idx = mg_map[vg]
                    return
            elif in_alt:
                self.effective_source_idx = 0
                return
        else:
            if in_alt and self.alt_group_source:
                vg = self.alt_group_source.get_value()
                if vg < len(mg_map):
                    self.effective_source_idx = mg_map[vg]
                    return
            elif in_main:
                self.effective_source_idx = 0
                return

        self.effective_source_idx = self.elem.get_value()

    @property
    def monitor_indicator(self) -> str | None:
        """Monitor group indicator for a hardware output label: None
        (plain label), "main" (active in Main), "alt" (active in Alt) or
        "strike" (in the inactive group only)."""
        e = self.elem
        if e.port_category != PC.HW or e.hw_type != HW.ANALOGUE:
            return None
        card = self.card
        main = card.elem(f"Main Group Output {e.lr_num} Playback Switch")
        alt = card.elem(f"Alt Group Output {e.lr_num} Playback Switch")
        if not main and not alt:
            return None

        state = card.speaker_switching
        in_main = bool(main and main.get_value())
        in_alt = bool(alt and alt.get_value())

        if state == SpeakerSwitch.OFF:
            return None
        if state == SpeakerSwitch.MAIN:
            return "main" if in_main else "strike" if in_alt else None
        return "alt" if in_alt else "strike" if in_main else None

    # routing

    def accepts(self, src: RoutingSrc | None) -> bool:
        """Can src be routed to this sink?"""
        if self.monitor_muted:
            return False
        # stereo source -> mono sink
        if src and src.is_linked and not self.is_linked:
            return False
        # mixer -> mixer only if supported
        return not (
            not self.card.mixer_has_mix_srcs
            and src
            and src.port_category == PC.MIX
            and self.elem.port_category == PC.MIX
        )

    def connect_source(self, src: RoutingSrc) -> bool:
        """Route src to this sink, handling stereo pairs. Returns True if
        routed."""
        if not self.accepts(src):
            return False
        _log.debug("route %s -> %s", src.name, self.name)

        partner = self.partner if self.is_linked else None
        if partner:
            src_partner = src.partner if src.is_linked else None
            if src_partner:
                # stereo -> stereo: L->L, R->R
                self.route_from(src.id)
                partner.route_from(src_partner.id)
                return True
            if not src.is_linked:
                # mono -> stereo: same source to both
                self.route_from(src.id)
                partner.route_from(src.id)
                return True

        self.route_from(src.id)
        return True

    def disconnect_source(self) -> None:
        """Route nothing to this sink (and its linked partner)."""
        target = self.routing_elem
        if target is None or target is not self.elem:
            return
        partner = self.partner if self.is_linked else None
        if partner:
            self.route_from(0)
            partner.route_from(0)
            return
        target.set_value(0)

    # labels in the settings

    def _source_name(self) -> str:
        src = self.card.src(self.elem.get_value())
        return src.display_name if src else "Off"

    @property
    def mixer_input_label(self) -> str:
        """ "Mixer 3 - Mic 1" (or just the source name for fixed inputs)."""
        if self.card.has_fixed_mixer_inputs:
            return self._source_name()
        return f"{self.generic_name} - {self._source_name()}"

    def mixer_input_pair_label(self, right: RoutingSnk) -> str:
        """Label of this and the right mixer input as a (potential) pair."""
        card = self.card
        src_l = card.src(self.elem.get_value())
        src_r = card.src(right.elem.get_value())
        if src_l and src_r and src_l.is_linked and src_l.partner is src_r:
            name = src_l.pair_display_name
        else:
            a, b = self._source_name(), right._source_name()
            name = a if a == b else f"{a} / {b}"
        if card.has_fixed_mixer_inputs:
            return name
        return f"{self.generic_pair_name} - {name}"

# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stereo linking of adjacent routing sources/sinks.

Each potential stereo pair (on the left channel) gets a simulated
boolean "Link" element and a BYTES "Name" element for the pair name.
Linking keeps the routing, enable state, mixer gains and monitor
group settings of both channels consistent.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from vermilion.core.asound import ELEM_TYPE_BOOLEAN, ELEM_TYPE_BYTES
from vermilion.core.card.elem import Elem
from vermilion.core.constants import HW, PC, PORT_CATEGORY_SHORT_NAMES, UiUpdate
from vermilion.core.features.names import MAX_PAIR_NAME_LEN
from vermilion.core.ports import Port, RoutingSnk, RoutingSrc
from vermilion.core.storage import state

if TYPE_CHECKING:
    from vermilion.core.card import Card

_log = logging.getLogger(__name__)

# channel helpers


# UI notification


def _pair_category_default(port_category: int, hw_type: int, pair_index: int, is_sink: bool) -> int:
    if is_sink:
        if port_category in (PC.HW, PC.PCM, PC.MIX):
            return 1
        if port_category == PC.DSP:
            return 0 if pair_index == 0 else 1
        return 0

    if port_category == PC.HW:
        if hw_type == HW.ANALOGUE:
            return 0 if pair_index == 0 else 1
        return 1
    if port_category in (PC.PCM, PC.MIX):
        return 1
    if port_category == PC.DSP:
        return 0 if pair_index == 0 else 1
    return 0


class StereoLinks:
    """The stereo links of a card: a link element (and a pair name
    element) on the left port of every potential pair, the first-run
    defaults, and keeping the routing, visibility, mixer gains, talkback
    and monitor groups of linked pairs consistent."""

    def __init__(self, card: Card) -> None:
        self.card = card
        if not card.serial or not card.routing_srcs:
            return
        self._init()
        for src in card.srcs_of(PC.MIX):
            self._register_talkback_sync(src)

    def _schedule_ui_update(self) -> None:
        self.card.emit("stereo-changed")
        self.card.schedule_ui_update(UiUpdate.MIXER_GRID)

    # linking side effects

    def _is_valid_stereo_src_connection(
        self,
        src_l: RoutingSrc | None,
        src_r: RoutingSrc | None,
        snk_l: RoutingSnk | None,
        snk_r: RoutingSnk | None,
    ) -> bool:
        if not (src_l and src_r and snk_l and snk_r):
            return False
        if snk_l.partner is not snk_r:
            return False
        return snk_l.effective_source_idx == src_l.id and snk_r.effective_source_idx == src_r.id

    def _validate_src_pair_routing(self, src_l: RoutingSrc, src_r: RoutingSrc) -> None:
        for snk in src_l.card.routing_snks:
            if snk.effective_source_idx not in (src_l.id, src_r.id):
                continue

            partner = snk.partner
            if not partner:
                # stereo source can't route to a mono sink
                snk.elem.set_value(0)
                continue

            snk_l, snk_r = (snk, partner) if snk.is_left else (partner, snk)

            if not self._is_valid_stereo_src_connection(src_l, src_r, snk_l, snk_r):
                snk_l.elem.set_value(0)
                snk_r.elem.set_value(0)
            else:
                link = snk_l.stereo_link_elem
                if link and not link.get_value():
                    link.set_value(1)

    def _validate_and_propagate_src_link(self, src: RoutingSrc) -> None:
        src_l = src.left
        src_r = src_l.partner if src_l else None
        if not src_l or not src_r:
            return

        if src_l.enable_elem and src_r.enable_elem:
            src_r.enable_elem.set_value(src_l.enable_elem.get_value())

        self._validate_src_pair_routing(src_l, src_r)
        self._schedule_ui_update()

    def _validate_snk_pair_routing(self, snk_l: RoutingSnk, snk_r: RoutingSnk) -> None:
        src_l_idx = snk_l.effective_source_idx
        src_r_idx = snk_r.effective_source_idx

        def clear() -> None:
            snk_l.elem.set_value(0)
            snk_r.elem.set_value(0)

        if src_l_idx == 0 or src_r_idx == 0:
            return clear()
        if src_l_idx >= len(self.card.routing_srcs) or src_r_idx >= len(self.card.routing_srcs):
            return clear()

        # both connected to the same source: valid mono->stereo
        if src_l_idx == src_r_idx:
            return

        src_l = self.card.routing_srcs[src_l_idx]
        src_r = self.card.routing_srcs[src_r_idx]

        if src_l.partner is not src_r or not src_l.is_left or src_r.is_left:
            return clear()

        link = src_l.stereo_link_elem
        if link and not link.get_value():
            link.set_value(1)

    def _validate_and_propagate_snk_link(self, snk: RoutingSnk) -> None:
        snk_l = snk.left
        snk_r = snk_l.partner if snk_l else None
        if not snk_l or not snk_r:
            return

        if snk_l.enable_elem and snk_r.enable_elem:
            snk_r.enable_elem.set_value(snk_l.enable_elem.get_value())

        self._validate_snk_pair_routing(snk_l, snk_r)
        self._schedule_ui_update()

    def _propagate_src_unlink(self, src: RoutingSrc) -> None:
        src_l = src.left
        src_r = src_l.partner if src_l else None
        if not src_l or not src_r:
            return
        for snk in self.card.routing_snks:
            if snk.effective_source_idx not in (src_l.id, src_r.id):
                continue
            partner = snk.partner
            if not partner:
                continue
            snk_l, snk_r = (snk, partner) if snk.is_left else (partner, snk)
            if self._is_valid_stereo_src_connection(src_l, src_r, snk_l, snk_r):
                link = snk_l.stereo_link_elem
                if link and link.get_value():
                    link.set_value(0)

        self._schedule_ui_update()

    def _propagate_snk_unlink(self, snk: RoutingSnk) -> None:
        snk_l = snk.left
        snk_r = snk_l.partner if snk_l else None
        if not snk_l or not snk_r:
            return
        src_l_idx = snk_l.effective_source_idx
        src_r_idx = snk_r.effective_source_idx
        n = len(self.card.routing_srcs)

        if src_l_idx == 0 or src_r_idx == 0 or src_l_idx >= n or src_r_idx >= n:
            return

        src_l = self.card.routing_srcs[src_l_idx]
        src_r = self.card.routing_srcs[src_r_idx]

        if src_l.partner is src_r and src_l.is_left:
            link = src_l.stereo_link_elem
            if link and link.get_value():
                link.set_value(0)

        self._schedule_ui_update()

    # mixer gain adjustments on link/unlink

    @staticmethod
    def _link_value(obj: RoutingSrc | RoutingSnk) -> bool:
        return bool(obj.link_elem and obj.link_elem.get_value())

    @staticmethod
    def _unlink(obj: RoutingSrc | RoutingSnk) -> bool:
        """Unlink a pair; returns True if it was linked."""
        if not obj.link_elem or not obj.link_elem.get_value():
            return False
        obj.link_elem.set_value(0)
        return True

    @staticmethod
    def _set_gain(elem: Elem | None, value: int) -> None:
        if elem:
            elem.set_value(value)

    @staticmethod
    def _copy_gain(src: Elem | None, dst: Elem | None) -> None:
        if src and dst:
            dst.set_value(src.get_value())

    def _mixer_crosspoints(
        self,
        port: Port,
    ) -> tuple[Callable[[int, int], Elem | None], list[Port | None]]:
        """For a mixer output (source) or input (sink): the gain element of a
        crosspoint by (index on the axis of port, index on the other axis),
        and the ports of the other axis by index."""
        g = self.card.mixer_gains
        others: list[Port | None]
        if port.is_src:
            others = [
                self.card.mixer_snk(i + 1) for i in range(self.card.routing_out_count[PC.MIX])
            ]
            return (lambda this, other: g[this][other]), others
        others = [self.card.mixer_src(i) for i in range(self.card.routing_in_count[PC.MIX])]
        return (lambda this, other: g[other][this]), others

    def _average_mixer_gains(self, left: Port, right: Port) -> None:
        """Mixer outputs or inputs linked: average gains so the pair behaves
        as stereo."""
        gain, others = self._mixer_crosspoints(left)
        this_l, this_r = left.mixer_index, right.mixer_index
        min_val = left.card.mixer_gain_min_val()

        for other_l, other in enumerate(others):
            other_linked = other is not None and other.is_linked

            if other and other_linked and other.is_left:
                # stereo->stereo: average diagonal, zero off-diagonal
                other_partner = other.partner
                if not other_partner:
                    continue
                other_r = other_partner.mixer_index

                diag_ll, diag_rr = gain(this_l, other_l), gain(this_r, other_r)
                if diag_ll and diag_rr:
                    avg = int((diag_ll.get_value() + diag_rr.get_value()) / 2)
                    diag_ll.set_value(avg)
                    diag_rr.set_value(avg)

                self._set_gain(gain(this_l, other_r), min_val)
                self._set_gain(gain(this_r, other_l), min_val)

            elif not other_linked:
                # mono: take the same-side diagonal value
                elem_l, elem_r = gain(this_l, other_l), gain(this_r, other_l)
                if not elem_l or not elem_r:
                    continue
                val = elem_l.get_value() if other_l % 2 == 0 else elem_r.get_value()
                elem_l.set_value(val)
                elem_r.set_value(val)

    def _distribute_mixer_gains(self, left: Port, right: Port) -> None:
        """Mixer outputs or inputs unlinked: copy diagonals to the
        off-diagonal slots."""
        gain, others = self._mixer_crosspoints(left)
        this_l, this_r = left.mixer_index, right.mixer_index

        for other_l, other in enumerate(others):
            if not other or not other.is_linked or not other.is_left:
                continue
            other_partner = other.partner
            if not other_partner:
                continue
            other_r = other_partner.mixer_index

            self._copy_gain(gain(this_l, other_l), gain(this_l, other_r))
            self._copy_gain(gain(this_r, other_r), gain(this_r, other_l))

    # monitor groups

    def _monitor_group_enum(self, routing_src_idx: int) -> int:
        try:
            return self.card.monitor_group_src_map.index(routing_src_idx)
        except ValueError:
            return -1

    def _sync_monitor_group_source_pair(self, source_l: Elem | None, source_r: Elem | None) -> None:
        """Set the R source enum from the L one, respecting linked sources."""
        if not source_l or not source_r or not self.card.monitor_group_src_map:
            return

        enum_val = source_l.get_value()
        if not 0 <= enum_val < len(self.card.monitor_group_src_map):
            return

        src_idx = self.card.monitor_group_src_map[enum_val]
        if src_idx <= 0 or src_idx >= len(self.card.routing_srcs):
            source_r.set_value(enum_val)
            return

        src = self.card.routing_srcs[src_idx]
        partner = src.partner

        if not partner or not src.is_linked:
            source_r.set_value(enum_val)
            return

        left, right = (src, partner) if src.is_left else (partner, src)
        left_enum = self._monitor_group_enum(left.id)
        right_enum = self._monitor_group_enum(right.id)

        if left_enum < 0 or right_enum < 0:
            source_r.set_value(enum_val)
            return

        source_l.set_value(left_enum)
        source_r.set_value(right_enum)

    def _sync_monitor_groups_on_link(self, snk_l: RoutingSnk, snk_r: RoutingSnk) -> None:

        for attr in ("main_group_switch", "alt_group_switch"):
            l, r = getattr(snk_l, attr), getattr(snk_r, attr)
            if l and r:
                r.set_value(l.get_value())

        self._sync_monitor_group_source_pair(snk_l.main_group_source, snk_r.main_group_source)
        self._sync_monitor_group_source_pair(snk_l.alt_group_source, snk_r.alt_group_source)

        for attr in ("main_group_trim", "alt_group_trim"):
            l, r = getattr(snk_l, attr), getattr(snk_r, attr)
            if l and r:
                avg = int((l.get_value() + r.get_value()) / 2)
                l.set_value(avg)
                r.set_value(avg)

    def _register_monitor_group_sync(self, snk_l: RoutingSnk) -> None:
        """Keep L/R monitor group controls in lockstep while linked."""
        snk_r = snk_l.partner
        if not snk_r:
            return

        for attr, is_source in (
            ("main_group_switch", False),
            ("alt_group_switch", False),
            ("main_group_source", True),
            ("alt_group_source", True),
            ("main_group_trim", False),
            ("alt_group_trim", False),
        ):
            left, right = getattr(snk_l, attr), getattr(snk_r, attr)
            if not left or not right:
                continue

            def sync(
                _elem: Elem, left: Elem = left, right: Elem = right, is_source: bool = is_source
            ) -> None:
                if not snk_l.is_linked:
                    return
                if is_source:
                    self._sync_monitor_group_source_pair(left, right)
                else:
                    v = left.get_value()
                    if right.get_value() != v:
                        right.set_value(v)

            left.connect("changed", sync)
            right.connect("changed", sync)

    # link state change handlers

    def _src_link_state_changed(self, src: RoutingSrc) -> None:
        src_l = src.left
        src_r = src_l.partner if src_l else None

        if self._link_value(src):
            self._validate_and_propagate_src_link(src)
            if src_l and src_r and src_l.port_category == PC.MIX:
                self._average_mixer_gains(src_l, src_r)
                # sync talkback state when linking (left wins)
                if src_l.talkback_elem and src_r.talkback_elem:
                    src_r.talkback_elem.set_value(src_l.talkback_elem.get_value())
        else:
            if src_l and src_r and src_l.port_category == PC.MIX:
                self._distribute_mixer_gains(src_l, src_r)
            self._propagate_src_unlink(src)

        if src_l and src_l.port_category == PC.MIX:
            self.card.emit("mixer-widgets-changed")

        # source link state affects the monitor group source dropdowns
        self.card.schedule_ui_update(UiUpdate.MONITOR_GROUPS)

        # the enable element callbacks are the single source of truth for
        # visibility
        if src_l and src_l.enable_elem:
            src_l.enable_elem.emit_changed()
        if src_r and src_r.enable_elem:
            src_r.enable_elem.emit_changed()

    def _snk_link_state_changed(self, snk: RoutingSnk) -> None:
        snk_l = snk.left
        snk_r = snk_l.partner if snk_l else None
        is_mix = snk_l is not None and snk_l.elem.port_category == PC.MIX
        is_hw_analogue = (
            snk_l is not None
            and snk_l.elem.port_category == PC.HW
            and snk_l.elem.hw_type == HW.ANALOGUE
        )

        if self._link_value(snk):
            self._validate_and_propagate_snk_link(snk)
            if snk_l and snk_r and is_mix:
                self._average_mixer_gains(snk_l, snk_r)
            if snk_l and snk_r and is_hw_analogue:
                self._sync_monitor_groups_on_link(snk_l, snk_r)
        else:
            if snk_l and snk_r and is_mix:
                self._distribute_mixer_gains(snk_l, snk_r)
            self._propagate_snk_unlink(snk)

        if is_mix:
            self.card.emit("mixer-widgets-changed")

        if is_hw_analogue:
            self.card.schedule_ui_update(UiUpdate.MONITOR_GROUPS)

        if snk_l and snk_l.enable_elem:
            snk_l.enable_elem.emit_changed()
        if snk_r and snk_r.enable_elem:
            snk_r.enable_elem.emit_changed()

    # element creation

    def _create_link_elems(self, port: Port) -> None:
        """Link and pair name elements, on the left port of a pair."""
        if not port.is_left or not port.partner:
            return
        link_key = port.control_name("Link", stereo=True)
        if not link_key:
            return
        port.link_elem = self.card.optional_elem(link_key, ELEM_TYPE_BOOLEAN)

        # mixer inputs don't have pair names (they show the connected source)
        pair_key = port.control_name("Name", stereo=True)
        if not pair_key or (not port.is_src and port.port_category == PC.MIX):
            return
        port.pair_name_elem = self.card.optional_elem(
            pair_key, ELEM_TYPE_BYTES, size=MAX_PAIR_NAME_LEN
        )

    def _register_callbacks(self, obj: Port) -> None:
        if not obj.link_elem:
            return

        if isinstance(obj, RoutingSrc):
            src = obj
            obj.link_elem.connect("changed", lambda _e: self._src_link_state_changed(src))
        elif isinstance(obj, RoutingSnk):
            snk = obj
            obj.link_elem.connect("changed", lambda _e: self._snk_link_state_changed(snk))

        if obj.pair_name_elem:
            obj.pair_name_elem.connect("changed", lambda _e: self._schedule_ui_update())

        # keep the right channel's enable state in sync while linked
        if obj.enable_elem:

            def enable_sync(elem: Elem) -> None:
                right = obj.partner if obj.is_linked else None
                if not right or not right.enable_elem:
                    return
                v = elem.get_value()
                if right.enable_elem.get_value() != v:
                    right.enable_elem.set_value(v)

            obj.enable_elem.connect("changed", enable_sync)

        if (
            isinstance(obj, RoutingSnk)
            and obj.elem.port_category == PC.HW
            and obj.elem.hw_type == HW.ANALOGUE
        ):
            self._register_monitor_group_sync(obj)

    @staticmethod
    def _register_talkback_sync(src: RoutingSrc) -> None:
        """Keep talkback state of a linked mixer output pair in sync."""
        if not src.talkback_elem or src.port_category != PC.MIX:
            return

        def sync(elem: Elem) -> None:
            if not src.is_linked:
                return
            partner = src.partner
            if not partner or not partner.talkback_elem:
                return
            v = elem.get_value()
            if partner.talkback_elem.get_value() != v:
                partner.talkback_elem.set_value(v)

        src.talkback_elem.connect("changed", sync)

    # first-run defaults

    def _determine_default_links(self) -> None:
        """Pick sensible link states on first run from the current routing.

        Called before callbacks are registered, so set_value() has no side
        effects.
        """
        log = _log.debug

        log("=== AUTO-STEREO-LINK: Starting determination ===")

        # phase 1: category defaults
        log("--- Phase 1: Setting category defaults ---")
        for src in self.card.routing_srcs:
            if not src.link_elem or not src.is_left:
                continue
            pair_index = (src.lr_num - 1) // 2
            v = _pair_category_default(src.port_category, src.hw_type, pair_index, False)
            log(f"  SRC {src.link_elem.name} lr={src.lr_num} pair={pair_index}: default={v}")
            src.link_elem.set_value(v)

        for snk in self.card.routing_snks:
            if not snk.link_elem or not snk.is_left:
                continue
            e = snk.elem
            pair_index = (e.lr_num - 1) // 2
            v = _pair_category_default(e.port_category, e.hw_type, pair_index, True)
            log(f"  SNK {snk.link_elem.name} lr={e.lr_num} pair={pair_index}: default={v}")
            snk.link_elem.set_value(v)

        # phase 2: fixpoint constraint propagation
        log("--- Phase 2: Fixpoint constraint propagation ---")
        min_val = self.card.mixer_gain_min_val()
        g = self.card.mixer_gains
        n_srcs = len(self.card.routing_srcs)

        def gval(elem: Elem | None) -> int:
            return elem.get_value() if elem else min_val

        changed = True
        iteration = 0
        while changed:
            changed = False
            iteration += 1
            log(f"  Iteration {iteration}:")

            # sink side: each stereo sink pair
            log("    [Sink-side checks]")
            for snk_l in self.card.routing_snks:
                if not snk_l.link_elem or not snk_l.is_left:
                    continue
                if not self._link_value(snk_l):
                    continue
                snk_r = snk_l.partner
                if not snk_r:
                    continue

                src_l_id = snk_l.elem.get_value()
                src_r_id = snk_r.elem.get_value()
                log(
                    f"      SNK pair {snk_l.link_elem.name} "
                    f"({PORT_CATEGORY_SHORT_NAMES[snk_l.elem.port_category]}): "
                    f"L->src[{src_l_id}] R->src[{src_r_id}]"
                )

                if src_l_id == 0 and src_r_id == 0:
                    log("        -> no connection, keeping stereo")
                    continue

                compatible = False
                src_l = src_r = None
                if (
                    src_l_id != 0
                    and src_r_id != 0
                    and src_l_id != src_r_id
                    and src_l_id < n_srcs
                    and src_r_id < n_srcs
                ):
                    src_l = self.card.routing_srcs[src_l_id]
                    src_r = self.card.routing_srcs[src_r_id]
                    if src_l.partner is src_r and src_l.is_left:
                        compatible = True

                if not compatible:
                    log("        -> DOWNGRADE sink (not compatible)")
                    snk_l.link_elem.set_value(0)
                    changed = True
                    if src_l and src_r and src_l.partner is src_r:
                        sle = src_l.stereo_link_elem
                        if sle and sle.get_value():
                            log("        -> DOWNGRADE source pair too")
                            sle.set_value(0)
                            changed = True
                elif src_l is not None:
                    sle = src_l.stereo_link_elem
                    if sle and not sle.get_value():
                        log("        -> compatible but source is mono, DOWNGRADE sink")
                        snk_l.link_elem.set_value(0)
                        changed = True

            # source side: each stereo source pair
            log("    [Source-side checks]")
            for src_l in self.card.routing_srcs:
                if not src_l.link_elem or not src_l.is_left:
                    continue
                if not self._link_value(src_l):
                    continue
                src_r = src_l.partner
                if not src_r:
                    continue

                downgrade = None
                for snk in self.card.routing_snks:
                    # fixed mixer inputs follow their source's link state
                    if snk.elem.port_category == PC.MIX and not snk.elem.writable():
                        continue
                    if snk.elem.get_value() not in (src_l.id, src_r.id):
                        continue

                    snk_left = snk.left
                    if not snk_left or not snk_left.link_elem:
                        downgrade = "sink has no left or no link_elem"
                        break
                    snk_right = snk_left.partner
                    if not snk_right:
                        downgrade = "sink has no right partner"
                        break

                    if (
                        snk_left.elem.get_value() != src_l.id
                        or snk_right.elem.get_value() != src_r.id
                    ):
                        downgrade = "sink pair routing doesn't match source pair"
                        if snk_left.link_elem.get_value():
                            log("          -> DOWNGRADE sink pair too")
                            snk_left.link_elem.set_value(0)
                            changed = True
                        break

                    if not self._link_value(snk_left):
                        downgrade = "sink pair is mono"
                        break

                if downgrade and src_l.link_elem.get_value():
                    log(f"        -> DOWNGRADE source: {downgrade}")
                    src_l.link_elem.set_value(0)
                    changed = True

            # mixer gain matrix checks
            mix_in_pairs = [
                s
                for s in self.card.routing_snks
                if s.link_elem and s.elem.port_category == PC.MIX and s.is_left
            ]
            mix_out_pairs = [
                s
                for s in self.card.routing_srcs
                if s.link_elem and s.port_category == PC.MIX and s.is_left
            ]

            # check 1: stereo-in x stereo-out needs zero crosstalk and equal
            # diagonals, else the input is taken as two mono ones
            for in_l in mix_in_pairs:
                if not self._link_value(in_l):
                    continue
                in_r = in_l.partner
                if not in_r:
                    continue
                idx_l, idx_r = in_l.elem.lr_num - 1, in_r.elem.lr_num - 1

                for out_l in mix_out_pairs:
                    if not self._link_value(out_l):
                        continue
                    out_r = out_l.partner
                    if not out_r:
                        continue
                    mix_l, mix_r = out_l.port_num, out_r.port_num

                    off_lr, off_rl = g[mix_l][idx_r], g[mix_r][idx_l]
                    crosstalk = (off_lr and off_lr.get_value() != min_val) or (
                        off_rl and off_rl.get_value() != min_val
                    )
                    mismatch = gval(g[mix_l][idx_l]) != gval(g[mix_r][idx_r])

                    # as two mono inputs, each with its pan, any gains fit
                    if (crosstalk or mismatch) and self._unlink(in_l):
                        changed = True

            # check 2: stereo-in x mono-out needs equal gains
            for in_l in mix_in_pairs:
                if not self._link_value(in_l):
                    continue
                in_r = in_l.partner
                if not in_r:
                    continue
                idx_l, idx_r = in_l.elem.lr_num - 1, in_r.elem.lr_num - 1

                for out in self.card.routing_srcs:
                    if out.port_category != PC.MIX:
                        continue
                    out_link = out.stereo_link_elem
                    if out_link and out_link.get_value():
                        continue
                    mix = out.port_num
                    if gval(g[mix][idx_l]) != gval(g[mix][idx_r]) and self._unlink(in_l):
                        changed = True

            # a mono input into a stereo mix may have different gains: that
            # is its pan position (see core.pan)

            if not changed:
                log(f"    No changes in iteration {iteration}, fixpoint reached")

        # phase 3: save all link values
        log("--- Phase 3: Final link states (saving) ---")
        lefts: list[RoutingSrc | RoutingSnk] = [s for s in self.card.routing_srcs if s.is_left]
        lefts += [s for s in self.card.routing_snks if s.is_left]
        for obj in lefts:
            if not obj.link_elem:
                continue
            v = 1 if obj.link_elem.get_value() else 0
            log(f"  {obj.link_elem.name}: {'STEREO' if v else 'mono'}")
            self.card.state.save(state.SECTION_CONTROLS, obj.link_elem.name, str(v))

        log("=== AUTO-STEREO-LINK: Determination complete ===\n")

    def _init(self) -> None:
        saved = self.card.state.load(state.SECTION_CONTROLS)

        for port in self.card.ports:
            self._create_link_elems(port)

        # First run: no Link keys saved and all link elements optional. If
        # any link element is real, the driver manages its own defaults.
        has_real = any(p.link_elem and not p.link_elem.optional for p in self.card.ports)
        _log.debug("link elements from the driver: %s", has_real)

        if not has_real:
            has_link_keys = any(k.endswith(" Link") for k in saved)
            if not has_link_keys:
                self._determine_default_links()

        # register callbacks after defaults are determined so that the
        # set_value() calls above don't trigger side effects
        for port in self.card.ports:
            self._register_callbacks(port)

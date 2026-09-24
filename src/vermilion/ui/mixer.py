# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixer window: gain matrix with stereo-aware controls, a column per
mix (mixer output) and a row per mixer input.

The mix labels on top and the input labels on the left (both with mute
and solo) are grids of their own, next to the scrolling matrix: they
scroll with it in one direction and stay in view in the other. Size groups keep their columns
and rows as wide and high as those of the matrix.

Inputs without a source and outputs which are not routed anywhere are
hidden unless "show all" is chosen.

The inputs are grouped by the kind of their source (hardware inputs,
playback, DSP, ...), each group below a heading row that folds it away.
The name of an input folds its row to the values of its cells, without
the faders. Both are remembered per device.
"""

from collections import defaultdict
from typing import TYPE_CHECKING, cast

from gi.repository import Adw, GLib, Gtk, Pango

from vermilion.core.constants import PC
from vermilion.core.scope import Scope
from vermilion.ui.resources import blueprint
from vermilion.ui.widgets.elem import ElemToggle
from vermilion.ui.widgets.gain import GainControl

if TYPE_CHECKING:
    from vermilion.core.ports import RoutingSnk, RoutingSrc
    from vermilion.ui.card_window import CardUI

LABEL_WIDTH = 10
KEY_SHOW_UNUSED = "mixer-show-unused"
# the titles of the folded groups of inputs, separated by commas
KEY_FOLDED = "mixer-folded"
# the inputs (mixer_index) whose rows are folded to the values
KEY_COMPACT = "mixer-compact"

# the groups of the inputs, by the kind of their source, in the order of
# the signal (as on the routing page)
INPUT_GROUPS = (
    (PC.HW, "Hardware Inputs"),
    (PC.PCM, "PCM Outputs"),
    (PC.DSP, "DSP Outputs"),
    (PC.MIX, "Mixer Outputs"),
    (PC.OFF, "Not Connected"),
)


def _column_label() -> Gtk.Label:
    """Label of a mix, above (or below) its column."""
    return Gtk.Label(
        wrap=True,
        justify=Gtk.Justification.CENTER,
        # a fixed width: e.g. "Mix A–B" in one line, longer names wrap
        width_chars=LABEL_WIDTH,
        max_width_chars=LABEL_WIDTH,
        ellipsize=Pango.EllipsizeMode.END,
        lines=2,
        valign=Gtk.Align.END,
    )


def _row_label() -> Gtk.Label:
    """Label of a mixer input, left (or right) of its row."""
    return Gtk.Label(
        ellipsize=Pango.EllipsizeMode.END,
        # e.g. "Analogue 1–2" in full next to the mute and solo buttons
        width_chars=12,
        max_width_chars=16,
        xalign=1.0,
    )


def _count(n: int, what: str) -> str:
    return f"{n} {what}{'' if n == 1 else 's'}"


class _GainCell:
    def __init__(
        self,
        widget: GainControl,
        mix_num: int,
        input_num: int,
        snks: list[RoutingSnk],
        srcs: list[RoutingSrc],
    ) -> None:
        self.widget = widget
        self.mix_num = mix_num
        self.input_num = input_num
        self.snks = snks
        self.srcs = srcs


@Gtk.Template(string=blueprint("mixer_panel"))
class MixerPanel(Gtk.Box):
    __gtype_name__ = "MixerPanel"

    # scrolls by itself (see DetachablePage)
    self_scrolling = True

    banner: Adw.Banner = Gtk.Template.Child()
    matrix: Gtk.Grid = Gtk.Template.Child()
    corner: Gtk.Label = Gtk.Template.Child()
    header_scroll: Gtk.ScrolledWindow = Gtk.Template.Child()
    header_grid: Gtk.Grid = Gtk.Template.Child()
    label_scroll: Gtk.ScrolledWindow = Gtk.Template.Child()
    label_grid: Gtk.Grid = Gtk.Template.Child()
    body_scroll: Gtk.ScrolledWindow = Gtk.Template.Child()
    grid: Gtk.Grid = Gtk.Template.Child()
    empty: Adw.StatusPage = Gtk.Template.Child()
    unavailable: Adw.StatusPage = Gtk.Template.Child()

    def __init__(self, card_ui: CardUI) -> None:
        super().__init__()
        self.card_ui = card_ui
        self.card = card = card_ui.card
        self.scope = card_ui.scope
        self._gain_scope = Scope()
        self.cells: list[_GainCell] = []
        self._size_groups: list[Gtk.SizeGroup] = []
        self.show_unused = card.prefs.view(KEY_SHOW_UNUSED) == "true"
        self._folded = set(filter(None, (card.prefs.view(KEY_FOLDED) or "").split(",")))
        compact = (card.prefs.view(KEY_COMPACT) or "").split(",")
        self._compact = {int(i) for i in compact if i.isdigit()}
        # the heading row of each group of inputs: its expander (with the
        # labels) and the band across the matrix
        self._sections: dict[str, tuple[Gtk.Expander, Gtk.Box]] = {}
        self._rebuild_id = 0

        # labels for the mixes (top/bottom) and inputs (left/right); the
        # top and left ones with mute and solo
        self.out_labels: dict[RoutingSrc, tuple[Gtk.Label, Gtk.Label]] = {}
        self.out_headers: dict[RoutingSrc, Gtk.Box] = {}
        for i in range(card.routing_in_count[PC.MIX]):
            src = card.mixer_src(i)
            if src:
                top, bottom = _column_label(), _column_label()
                self.out_labels[src] = (top, bottom)
                self.out_headers[src] = self._header(src, top, above=True)
        self.in_labels: dict[RoutingSnk, tuple[Gtk.Label, Gtk.Label]] = {}
        self.in_headers: dict[RoutingSnk, Gtk.Box] = {}
        self.in_expanders: dict[RoutingSnk, Gtk.Expander] = {}
        for snk in card.snks_of(PC.MIX):
            left, right = _row_label(), _row_label()
            self.in_labels[snk] = (left, right)
            # the name folds the row
            expander = Gtk.Expander(
                label_widget=left,
                expanded=snk.mixer_index not in self._compact,
                hexpand=True,
                valign=Gtk.Align.CENTER,
                tooltip_text="Fold or unfold the faders of this input",
            )
            expander.connect("notify::expanded", self._on_compact, snk.mixer_index)
            self.in_expanders[snk] = expander
            self.in_headers[snk] = self._header(snk, expander, above=False)

        self.corner.set_markup('<span line_height="1.8">Mixes →</span>\nInputs ↓')

        # the label grids scroll with the matrix
        for scroll, orientation in (
            (self.header_scroll, Gtk.Orientation.HORIZONTAL),
            (self.label_scroll, Gtk.Orientation.VERTICAL),
        ):
            self._sync_adjustments(
                self._adjustment(self.body_scroll, orientation), scroll, orientation
            )

        s = self.scope
        s.connect(card, "mixer-widgets-changed", lambda _c: self.recreate_widgets())
        s.connect(card, "routing-changed", lambda _c: self._routing_changed())
        s.connect(card, "availability-changed", lambda _c: self._update_availability())
        # hiding the source of an input hides its row
        s.connect(card, "port-visibility-changed", lambda _c, _pc, _src: self.rebuild_grid())
        for src in card.routing_srcs:
            s.connect(src, "name-changed", lambda _src: self.update_labels())
        for port in (*self.in_labels, *self.out_labels):
            for elem in (port.mute_elem, port.solo_elem):
                if elem:
                    s.watch(elem, lambda _e: self._update_silenced())
        s.on_close(self._gain_scope.close)
        s.on_close(self._cancel_rebuild)

        self._populate_gains()
        self.update_labels()
        self.rebuild_grid()
        self._update_availability()

    # scrolling

    @staticmethod
    def _adjustment(scroll: Gtk.ScrolledWindow, orientation: Gtk.Orientation) -> Gtk.Adjustment:
        if orientation == Gtk.Orientation.HORIZONTAL:
            return scroll.get_hadjustment()
        return scroll.get_vadjustment()

    def _sync_adjustments(
        self, body: Gtk.Adjustment, scroll: Gtk.ScrolledWindow, orientation: Gtk.Orientation
    ) -> None:
        """Scroll the label grid with the matrix, and the other way round
        (e.g. with the mouse wheel over the labels)."""
        labels = self._adjustment(scroll, orientation)
        body.connect("value-changed", lambda a: labels.set_value(a.get_value()))
        labels.connect("value-changed", lambda a: body.set_value(a.get_value()))

    # gain widgets

    def _header(self, port: RoutingSnk | RoutingSrc, label: Gtk.Widget, above: bool) -> Gtk.Box:
        """The label of a mix (above its column, the mute and solo buttons
        below the label) or of an input (left of its row, the buttons
        next to the label)."""
        if above:
            header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            header.add_css_class("mixer-column")
            label.set_vexpand(True)
        else:
            header = Gtk.Box(spacing=6)
            header.add_css_class("mixer-row")
            label.set_hexpand(True)
            label.set_valign(Gtk.Align.CENTER)
        header.append(label)
        buttons = self._switch_buttons(port)
        if buttons:
            header.append(buttons)
        return header

    def _switch_buttons(self, port: RoutingSnk | RoutingSrc) -> Gtk.Box | None:
        """Mute and solo buttons of a mixer input or mix."""
        if not (port.mute_elem and port.solo_elem):
            return None
        if port.is_src:
            tips = ("Mute this mix", "Solo: mute all mixes which are not soloed")
        else:
            tips = ("Mute this input in all mixes", "Solo: mute all inputs which are not soloed")
        buttons = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        for elem, text, css, tooltip in (
            (port.mute_elem, "M", "mute-button", tips[0]),
            (port.solo_elem, "S", "solo-button", tips[1]),
        ):
            button = ElemToggle(self.scope, elem, text, tooltip=tooltip)
            # sized by style.css, not by the unstyled text
            button.set_size_request(-1, -1)
            button.add_css_class("circular")
            button.add_css_class(css)
            buttons.append(button)
        return buttons

    def _populate_gains(self) -> None:
        card = self.card
        g = card.mixer_gains
        scope = self._gain_scope

        for mix_num in range(card.routing_in_count[PC.MIX]):
            mix_src = card.mixer_src(mix_num)
            if not mix_src or not mix_src.should_display:
                continue
            out_linked = mix_src.is_linked
            mix_src_r = mix_src.partner if out_linked else None
            mix_r = mix_src_r.port_num if mix_src_r else -1

            for input_num in range(card.routing_out_count[PC.MIX]):
                snk = card.mixer_snk(input_num + 1)
                if not snk or not snk.should_display:
                    continue
                in_linked = snk.is_linked
                snk_r = snk.partner if in_linked else None
                in_r = snk_r.elem.lr_num - 1 if snk_r else -1

                # stereo mix: pan (mono input) or balance (stereo input)
                pan_label = None
                if in_linked and out_linked:
                    coords = [(mix_num, input_num), (mix_r, in_r)]
                    pan_label = "Balance"
                elif in_linked:
                    coords = [(mix_num, input_num), (mix_num, in_r)]
                elif out_linked:
                    coords = [(mix_num, input_num), (mix_r, input_num)]
                    pan_label = "Pan"
                else:
                    coords = [(mix_num, input_num)]

                elems = [e for m, i in coords if m >= 0 and i >= 0 and (e := g[m][i])]
                if not elems:
                    continue

                w = GainControl(
                    scope,
                    elems,
                    zero_is_off=True,
                    show_level=True,
                    can_control=False,
                    height=100,
                    fader_law=True,
                    # both gains of the pair are needed for pan
                    pan_label=pan_label if len(elems) == 2 else None,
                )
                # the cell with its lines to the next row and column
                w.add_css_class("mixer-cell")
                w.set_valign(Gtk.Align.FILL)
                w.set_halign(Gtk.Align.FILL)

                labels = list(self.out_labels.get(mix_src, ())) + list(self.in_labels.get(snk, ()))
                motion = Gtk.EventControllerMotion()
                motion.connect("enter", self._hover, labels, True)
                motion.connect("leave", self._hover, labels, False)
                w.add_controller(motion)

                self.cells.append(
                    _GainCell(
                        w,
                        mix_num,
                        input_num,
                        [snk, snk_r] if snk_r else [snk],
                        [mix_src, mix_src_r] if mix_src_r else [mix_src],
                    )
                )
        # faders in line: cells without pan keep its space if others have one
        if any(cell.widget.pan_label for cell in self.cells):
            for cell in self.cells:
                if not cell.widget.pan_label:
                    placeholder = cell.widget.pan_box
                    placeholder.set_visible(True)
                    # as high as a pan control with its value and centre mark
                    cell.widget.pan_value.set_label("C")
                    cell.widget.pan_scale.add_mark(0.0, Gtk.PositionType.TOP, None)
                    placeholder.set_opacity(0)
                    placeholder.set_can_target(False)
                    placeholder.set_sensitive(False)
        self._update_silenced()

    @staticmethod
    def _hover(_controller: Gtk.EventControllerMotion, *args: object) -> None:
        # "enter" passes the pointer position before the user data
        labels = cast(list[Gtk.Label], args[-2])
        on = bool(args[-1])
        for label in labels:
            if on:
                label.add_css_class("mixer-label-hover")
            else:
                label.remove_css_class("mixer-label-hover")

    def _update_silenced(self) -> None:
        """Cells of muted (or not soloed) inputs and mixes can't be changed."""
        mute = self.card.mixer_mute
        for cell in self.cells:
            ports = [*cell.snks, *cell.srcs]
            silenced = bool(mute and any(mute.silenced(p) for p in ports))
            cell.widget.set_sensitive(not silenced)

    def recreate_widgets(self) -> None:
        for cell in self.cells:
            if cell.widget.get_parent() is self.grid:
                self.grid.remove(cell.widget)
        self._gain_scope.close()
        self._gain_scope = Scope()
        self.cells = []
        self._populate_gains()
        self.update_labels()
        self.rebuild_grid()

    # labels

    def update_labels(self) -> None:
        card = self.card
        for src, (left, right) in self.out_labels.items():
            if not src.should_display:
                continue
            name = src.pair_display_name if src.is_linked else src.mixer_label
            for label in (left, right):
                label.set_text(name)
                label.set_tooltip_text(name)

        for snk, (top, bottom) in self.in_labels.items():
            if not snk.should_display:
                continue
            snk_src = card.src(snk.elem.get_value())
            if not snk_src:
                continue
            if snk.is_linked and snk_src.is_linked:
                name = snk_src.pair_display_name
            else:
                name = snk_src.display_name
            for label in (top, bottom):
                label.set_text(name)
                label.set_tooltip_text(name)

    def _routing_changed(self) -> None:
        self.update_labels()
        # what is used changes with the routing
        self.rebuild_grid()

    # which inputs and outputs are shown

    def _input_used(self, snk: RoutingSnk) -> bool:
        """Has the input (or its pair) a source?"""
        if self.card.has_fixed_mixer_inputs:
            return True
        pair = [snk, snk.partner] if snk.is_linked and snk.partner else [snk]
        return any(s.elem.get_value() != 0 for s in pair)

    def _source_hidden(self, snk: RoutingSnk) -> bool:
        """Is the source of an input hidden (in the settings)?"""
        src = self.card.src(snk.elem.get_value())
        if not src or src.id == 0:
            return False
        # a linked pair is shown or hidden by its left channel
        left = src.left if src.is_linked else src
        return not (left or src).enabled

    def _output_used(self, src: RoutingSrc) -> bool:
        """Is the output (or its pair) routed somewhere?"""
        ids = {src.id}
        if src.is_linked and src.partner:
            ids.add(src.partner.id)
        return any(s.elem.get_value() in ids for s in self.card.routing_snks)

    @Gtk.Template.Callback()
    def _on_toggle_unused(self, *_args: object) -> None:
        self.show_unused = not self.show_unused
        self.card.prefs.set_view(KEY_SHOW_UNUSED, "true" if self.show_unused else "false")
        self.rebuild_grid()

    def _update_banner(self, hidden_in: int, hidden_out: int, unused: bool) -> None:
        if hidden_in or hidden_out:
            parts = [
                _count(n, what)
                for n, what in ((hidden_in, "unused input"), (hidden_out, "unused output"))
                if n
            ]
            self.banner.set_title(f"{' and '.join(parts)} hidden")
            self.banner.set_button_label("Show All")
        else:
            self.banner.set_title("Showing unused inputs and outputs")
            self.banner.set_button_label("Hide Unused")
        self.banner.set_revealed(bool(hidden_in or hidden_out or (self.show_unused and unused)))

    # groups of inputs

    def _group_of(self, snk: RoutingSnk) -> str:
        src = self.card.src(snk.elem.get_value())
        pc = src.port_category if src and src.id else PC.OFF
        return next(title for group_pc, title in INPUT_GROUPS if group_pc == pc)

    def _grouped(self, snks: list[RoutingSnk]) -> list[tuple[str, list[RoutingSnk]]]:
        """The inputs by group, in the order of INPUT_GROUPS (and in their
        own order within a group)."""
        groups: dict[str, list[RoutingSnk]] = defaultdict(list)
        for snk in snks:
            groups[self._group_of(snk)].append(snk)
        return [(title, groups[title]) for _pc, title in INPUT_GROUPS if groups[title]]

    def _section(self, title: str) -> tuple[Gtk.Expander, Gtk.Box]:
        """The heading row of a group (created once, kept across rebuilds)."""
        if title not in self._sections:
            expander = Gtk.Expander(label=title, expanded=title not in self._folded)
            label = expander.get_label_widget()
            if label:
                label.add_css_class("heading")
            expander.add_css_class("mixer-section")
            expander.connect("notify::expanded", self._on_fold, title)
            band = Gtk.Box()
            band.add_css_class("mixer-section-band")
            self._sections[title] = (expander, band)
        return self._sections[title]

    def _on_fold(self, expander: Gtk.Expander, _pspec: object, title: str) -> None:
        if expander.get_expanded():
            self._folded.discard(title)
        else:
            self._folded.add(title)
        self.card.prefs.set_view(KEY_FOLDED, ",".join(sorted(self._folded)))
        # not while the expander handles its click
        if not self._rebuild_id:
            self._rebuild_id = GLib.idle_add(self._idle_rebuild)

    def _idle_rebuild(self) -> bool:
        self._rebuild_id = 0
        self.rebuild_grid()
        return GLib.SOURCE_REMOVE

    def _on_compact(self, expander: Gtk.Expander, _pspec: object, input_num: int) -> None:
        if expander.get_expanded():
            self._compact.discard(input_num)
        else:
            self._compact.add(input_num)
        self.card.prefs.set_view(KEY_COMPACT, ",".join(map(str, sorted(self._compact))))
        for cell in self.cells:
            if cell.input_num == input_num:
                cell.widget.set_compact(input_num in self._compact)

    @Gtk.Template.Callback()
    def _on_collapse_all(self, *_args: object) -> None:
        for expander in self.in_expanders.values():
            expander.set_expanded(False)

    @Gtk.Template.Callback()
    def _on_expand_all(self, *_args: object) -> None:
        for expander, _band in self._sections.values():
            expander.set_expanded(True)
        # groups not shown yet (no heading row created)
        if self._folded:
            self._folded.clear()
            self.card.prefs.set_view(KEY_FOLDED, "")
            self.rebuild_grid()
        for expander in self.in_expanders.values():
            expander.set_expanded(True)

    def _cancel_rebuild(self) -> None:
        if self._rebuild_id:
            GLib.source_remove(self._rebuild_id)
            self._rebuild_id = 0

    # layout

    def _clear(self) -> None:
        for group in self._size_groups:
            for widget in list(group.get_widgets()):
                group.remove_widget(widget)
        self._size_groups = []
        for grid in (self.grid, self.header_grid, self.label_grid):
            child = grid.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                grid.remove(child)
                child = nxt

    def _size_group(self, mode: Gtk.SizeGroupMode, widgets: list[Gtk.Widget]) -> None:
        group = Gtk.SizeGroup(mode=mode)
        for widget in widgets:
            group.add_widget(widget)
        self._size_groups.append(group)

    def rebuild_grid(self) -> None:
        card = self.card
        self._clear()
        show_br = card.prefs.show_bottom_right_labels

        shown_srcs = [s for s in self.out_labels if s.enabled and s.should_display]
        shown_snks = [
            s
            for s in self.in_labels
            if s.enabled and s.should_display and not self._source_hidden(s)
        ]
        used_srcs = [s for s in shown_srcs if self._output_used(s)]
        used_snks = [s for s in shown_snks if self._input_used(s)]
        srcs = shown_srcs if self.show_unused else used_srcs
        snks = shown_snks if self.show_unused else used_snks

        # a column per mix; a heading row per group of inputs, then a row per
        # input of the group unless it is folded
        cols = {src.port_num: i for i, src in enumerate(srcs)}
        rows: dict[int, int] = {}

        row_widgets: dict[int, list[Gtk.Widget]] = defaultdict(list)
        col_widgets: dict[int, list[Gtk.Widget]] = {i: [] for i in range(len(cols))}

        n_rows = 0
        for title, group in self._grouped(snks) if cols else []:
            expander, band = self._section(title)
            self.label_grid.attach(expander, 0, n_rows, 1, 1)
            self.grid.attach(band, 0, n_rows, len(cols), 1)
            row_widgets[n_rows] += [expander, band]
            n_rows += 1
            if title in self._folded:
                continue
            for snk in group:
                _left, right = self.in_labels[snk]
                rows[snk.mixer_index] = n_rows
                header = self.in_headers[snk]
                self.label_grid.attach(header, 0, n_rows, 1, 1)
                row_widgets[n_rows].append(header)
                if show_br:
                    self.grid.attach(right, len(cols), n_rows, 1, 1)
                n_rows += 1

        for src in srcs:
            _top, bottom = self.out_labels[src]
            col = cols[src.port_num]
            header = self.out_headers[src]
            self.header_grid.attach(header, col, 0, 1, 1)
            col_widgets[col].append(header)
            if show_br:
                self.grid.attach(bottom, col, n_rows, 1, 1)

        # the columns keep their widths without cells (all groups folded)
        for col in range(len(cols)):
            strut = Gtk.Box()
            self.grid.attach(strut, col, n_rows + 1, 1, 1)
            col_widgets[col].append(strut)

        for cell in self.cells:
            cell_col = cols.get(cell.mix_num)
            cell_row = rows.get(cell.input_num)
            cell.widget.set_compact(cell.input_num in self._compact)
            if cell_row is not None and cell_col is not None:
                self.grid.attach(cell.widget, cell_col, cell_row, 1, 1)
                row_widgets[cell_row].append(cell.widget)
                col_widgets[cell_col].append(cell.widget)

        for widgets in col_widgets.values():
            self._size_group(Gtk.SizeGroupMode.HORIZONTAL, widgets)
        for widgets in row_widgets.values():
            self._size_group(Gtk.SizeGroupMode.VERTICAL, widgets)

        unused = len(used_srcs) < len(shown_srcs) or len(used_snks) < len(shown_snks)
        hidden_in = 0 if self.show_unused else len(shown_snks) - len(used_snks)
        hidden_out = 0 if self.show_unused else len(shown_srcs) - len(used_srcs)
        self._update_banner(hidden_in, hidden_out, unused)
        self.empty.set_visible(bool(shown_srcs and shown_snks) and not (srcs and snks))

    def _update_availability(self) -> None:
        available = self.card.mixer_available
        self.matrix.set_opacity(1.0 if available else 0.3)
        self.unavailable.set_visible(not available)

    # levels

    def update_levels(self) -> None:
        card = self.card
        for cell in self.cells:
            # post-gain level: the loudest connected source plus the gain
            level = None
            for snk in cell.snks:
                src = card.src(snk.elem.get_value())
                if not src or src.id == 0:
                    continue
                src_level = card.src_level_db(src)
                if level is None or src_level > level:
                    level = src_level
            if level is not None:
                level += cell.widget.gain_db()
            cell.widget.set_level(level)

# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Levels window: a level meter for every meter the driver provides.

The meters are grouped (e.g. "Hardware Outputs") in the order of the
signal: what comes into the interface, what processes it (DSP, mixer),
what goes out. Each group is a table of cells with a meter each, with
the lines of the mixer, all cells equally wide, in as many (equally
full) rows as the page needs, each row with a dB scale; its heading
folds it away (remembered per device).
Above every meter is its peak level of the last second as a number,
below it the name of its port and, for an output, what feeds it.
Meters of ports hidden in the settings are left out, and those of
outputs without a source unless "show all" is chosen.
"""

import logging
import math
import re
import time
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

from gi.repository import Adw, Graphene, Gsk, Gtk, Pango, PangoCairo

from vermilion.core.constants import PC, PC_COUNT, PORT_CATEGORY_NAMES
from vermilion.core.ports import RoutingSnk
from vermilion.ui.resources import blueprint
from vermilion.ui.widgets.gain import LEVEL_MIN_DB, set_level_db, setup_level_bar
from vermilion.ui.widgets.group import ControlsGroup

if TYPE_CHECKING:
    import cairo

    from vermilion.core.ports import Port
    from vermilion.ui.card_window import CardUI

_log = logging.getLogger(__name__)

METER_HEIGHT = 120
SPACING = 4
# the padding of a meter in its cell, and the lines between the cells (as
# those of the mixer: the text colour at 12 %)
CELL_PAD_X = 8
CELL_PAD_Y = 10
LINE = 1
LINE_ALPHA = 0.12
SCALE_DB = (0, -12, -24, -36, -48, -60)
# how long the number shows the peak level (seconds)
PEAK_HOLD = 1.0
# the level of a meter without signal
NO_SIGNAL_DB = -80.0
# the names below a meter (the port, its source): lines, and characters
# per line, as many as the longest names of the page need within these
NAME_LINES = 2
NAME_CHARS = 9
NAME_CHARS_MAX = 14
KEY_SHOW_UNUSED = "levels-show-unused"
# the titles of the folded groups, separated by commas
KEY_FOLDED = "levels-folded"

# the groups of the sources, then those of the sinks, in the order of the
# signal: in, processing, out
SRC_GROUPS = ((PC.HW, "Hardware Inputs"), (PC.PCM, "PCM Outputs"))
SNK_ORDER = (PC.DSP, PC.MIX, PC.HW, PC.PCM)


def _split_label(label: str) -> tuple[str, int]:
    """ "Source Analogue 1" -> ("Source Analogue", 1), "Sink Mix A" -> (.., 1)."""
    head, _, tail = label.rpartition(" ")
    if tail.isdigit():
        return head, int(tail)
    if len(tail) == 1 and "A" <= tail <= "Z":
        return head, ord(tail) - ord("A") + 1
    return label, 1


def format_level(level_db: float) -> str:
    """ "−12", or "−∞" without signal."""
    if math.isnan(level_db) or level_db <= NO_SIGNAL_DB:
        return "−∞"
    value = round(level_db)
    return f"−{-value}" if value < 0 else str(value)


class _Scale(Gtk.DrawingArea):
    """dB labels next to the meters, at the heights of the levels."""

    def __init__(self) -> None:
        super().__init__(content_width=28, content_height=METER_HEIGHT)
        self.add_css_class("caption")
        self.add_css_class("dim-label")
        self.set_draw_func(self._draw)

    def _draw(
        self,
        _area: Gtk.DrawingArea,
        cr: cairo.Context,  # type: ignore[type-arg]
        width: int,
        height: int,
    ) -> None:
        color = self.get_color()
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        for db in SCALE_DB:
            layout = self.create_pango_layout(format_level(db) if db else "0")
            text_w, text_h = layout.get_pixel_size()
            y = (db / LEVEL_MIN_DB) * height - text_h / 2
            cr.move_to(width - text_w, max(0.0, min(height - text_h, y)))
            PangoCairo.show_layout(cr, layout)


def _fits(text: str, chars: int, lines: int) -> bool:
    """Does text fit into lines of chars, broken at spaces and after
    slashes (as "Mic/Line/Inst 1")?"""
    pieces = [
        (piece, i == 0)
        for word in text.split()
        for i, piece in enumerate(re.findall(r"[^/]*/|[^/]+", word))
    ]
    used, length = 1, 0
    for piece, new_word in pieces:
        add = len(piece) + (1 if new_word and length else 0)
        if length and length + add > chars:
            used, length = used + 1, len(piece)
        else:
            length += add
    return used <= lines and all(len(piece) <= chars for piece, _ in pieces)


def _chars_needed(texts: list[str]) -> int:
    """Characters per line the names need (see NAME_CHARS)."""
    for chars in range(NAME_CHARS, NAME_CHARS_MAX):
        if all(_fits(text, chars, NAME_LINES) for text in texts):
            return chars
    return NAME_CHARS_MAX


def _name_label(css: list[str], lines: int) -> Gtk.Label:
    return Gtk.Label(
        wrap=True,
        lines=lines,
        ellipsize=Pango.EllipsizeMode.END,
        justify=Gtk.Justification.CENTER,
        width_chars=NAME_CHARS,
        max_width_chars=NAME_CHARS,
        valign=Gtk.Align.START,
        css_classes=css,
    )


class _Meter(Gtk.Box):
    """The cell of a port, or of a linked stereo pair: a level bar per
    channel with its peak level above, the name of the port (or pair) and
    of its source below."""

    def __init__(self, channels: int) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=SPACING)
        self.value = Gtk.Box(spacing=SPACING, halign=Gtk.Align.CENTER, homogeneous=True)
        bars = Gtk.Box(spacing=3 * SPACING, halign=Gtk.Align.CENTER)
        self.values: list[Gtk.Label] = []
        self.bars: list[Gtk.LevelBar] = []
        for _ in range(channels):
            value = Gtk.Label(label="−∞", width_chars=3, css_classes=["caption", "numeric"])
            bar = Gtk.LevelBar(
                orientation=Gtk.Orientation.VERTICAL,
                inverted=True,
                mode=Gtk.LevelBarMode.CONTINUOUS,
                halign=Gtk.Align.CENTER,
                height_request=METER_HEIGHT,
                width_request=8,
            )
            setup_level_bar(bar)
            self.value.append(value)
            bars.append(bar)
            self.values.append(value)
            self.bars.append(bar)
        self.name = _name_label(["caption"], NAME_LINES)
        self.source = _name_label(["caption", "dim-label"], NAME_LINES)
        for widget in (self.value, bars, self.name, self.source):
            self.append(widget)
        self.peaks = [NO_SIGNAL_DB] * channels
        self.peak_times = [0.0] * channels

    def set_names(self, name: str, source: str | None) -> None:
        """The name of the port and of its source (None: no line)."""
        self.name.set_label(name)
        self.source.set_label(f"← {source}" if source else "")
        self.set_tooltip_text(f"{name} ← {source}" if source else name)

    def set_name_chars(self, chars: int) -> None:
        for label in (self.name, self.source):
            label.set_width_chars(chars)
            label.set_max_width_chars(chars)

    def set_level(self, channel: int, level_db: float, now: float) -> None:
        set_level_db(self.bars[channel], level_db)
        if level_db >= self.peaks[channel] or now - self.peak_times[channel] > PEAK_HOLD:
            self.peaks[channel], self.peak_times[channel] = level_db, now
            text = format_level(level_db)
            label = self.values[channel]
            if label.get_label() != text:
                label.set_label(text)


class _MeterFlow(Gtk.Widget):
    """Equally wide meters in cells of a table, in as many rows as the
    width needs, each row with a scale at its start (left of the table).
    The lines of the table are those of the mixer (see style.css)."""

    def __init__(self) -> None:
        super().__init__(hexpand=True)
        self.meters: list[_Meter] = []
        # one per possible row
        self.scales: list[_Scale] = []
        # the cells of the last allocation (x, y, width, height) for the lines
        self._cells: list[tuple[float, float, float, float]] = []

    def add(self, meter: _Meter) -> None:
        meter.set_parent(self)
        self.meters.append(meter)
        scale = _Scale()
        scale.set_parent(self)
        self.scales.append(scale)

    def clear(self) -> None:
        for child in (*self.meters, *self.scales):
            child.unparent()
        self.meters, self.scales = [], []
        self._cells = []
        self.queue_resize()

    def do_dispose(self) -> None:
        self.clear()

    def do_get_request_mode(self) -> Gtk.SizeRequestMode:
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def _shown(self) -> list[_Meter]:
        return [m for m in self.meters if m.get_visible()]

    def _sizes(self) -> tuple[int, int, int]:
        """Width and height of a cell, width of a scale (with its gap)."""
        width = height = 0
        for meter in self.meters:
            _, nat = meter.get_preferred_size()
            width, height = max(width, nat.width), max(height, nat.height)
        scale_w = self.scales[0].get_preferred_size()[1].width if self.scales else 0
        return width + 2 * CELL_PAD_X, height + 2 * CELL_PAD_Y, scale_w + SPACING

    def _per_row(self, width: int) -> int:
        """Cells per row: as few rows as the width allows, equally full."""
        cell_w, _, scale_w = self._sizes()
        fit = max(1, (width - scale_w - LINE) // cell_w)
        n = max(1, len(self._shown()))
        return math.ceil(n / math.ceil(n / fit))

    def do_measure(self, orientation: Gtk.Orientation, for_size: int) -> tuple[int, int, int, int]:
        cell_w, cell_h, scale_w = self._sizes()
        n = len(self._shown())
        if orientation == Gtk.Orientation.HORIZONTAL:
            minimum = scale_w + cell_w + LINE
            natural = scale_w + n * cell_w + LINE
            return minimum, natural, -1, -1
        width = for_size if for_size >= 0 else scale_w + n * cell_w + LINE
        rows = math.ceil(n / self._per_row(width)) if n else 0
        height = rows * cell_h + LINE if rows else 0
        return height, height, -1, -1

    @staticmethod
    def _place(child: Gtk.Widget, x: float, y: float, width: int, height: int) -> None:
        transform = Gsk.Transform.new().translate(Graphene.Point.alloc().init(x, y))
        child.allocate(width, height, -1, transform)

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        self._cells = []
        shown = self._shown()
        if not shown:
            return
        cell_w, cell_h, scale_w = self._sizes()
        meter_w, meter_h = cell_w - 2 * CELL_PAD_X, cell_h - 2 * CELL_PAD_Y
        per_row = self._per_row(width)
        rows = math.ceil(len(shown) / per_row)
        # the cells as wide as those of the other groups (as the columns of
        # the mixer), not spread over the width
        for i, meter in enumerate(shown):
            row, col = divmod(i, per_row)
            x, y = scale_w + col * cell_w, row * cell_h
            self._cells.append((x, y, cell_w, cell_h))
            self._place(meter, x + CELL_PAD_X, y + CELL_PAD_Y, meter_w, meter_h)
        # the scale beside the bars (below the peak level)
        bar_y = CELL_PAD_Y + self.meters[0].value.get_preferred_size()[1].height + SPACING
        for row, scale in enumerate(self.scales):
            scale.set_child_visible(row < rows)
            if row < rows:
                self._place(scale, 0, row * cell_h + bar_y, scale_w - SPACING, METER_HEIGHT)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        Gtk.Widget.do_snapshot(self, snapshot)
        # the lines of each cell: all four sides, each line drawn once
        color = self.get_color()
        color.alpha *= LINE_ALPHA
        lines = set()
        for x, y, w, h in self._cells:
            x0, y0, x1, y1 = round(x), round(y), round(x + w), round(y + h)
            lines |= {(x0, y0, x1 - x0, LINE), (x0, y1, x1 - x0, LINE)}
            lines |= {(x0, y0, LINE, y1 - y0 + LINE), (x1, y0, LINE, y1 - y0 + LINE)}
        for x, y, w, h in lines:
            snapshot.append_color(color, Graphene.Rect.alloc().init(x, y, w, h))


# the level of a channel: an index of card.routing_levels, or a function
# (for the sources, measured at a sink)
type Level = int | Callable[[], float]


class _Channel:
    """A meter of the driver: its name (for a port unknown), port and level."""

    def __init__(self, name: str, port: Port | None, level: Level) -> None:
        self.name = name
        self.port = port
        self.level = level


class _Cell:
    """A cell of the table: a channel, or the two of a linked pair."""

    def __init__(self, meter: _Meter, channels: list[_Channel]) -> None:
        self.meter = meter
        self.channels = channels


class _Group:
    """The meters of a kind of port, in a table of equally wide cells."""

    def __init__(self, box: Gtk.Box, title: str) -> None:
        self.title = title
        self.channels: list[_Channel] = []
        self.cells: list[_Cell] = []
        self.flow = _MeterFlow()
        self.widget = ControlsGroup(title, self.flow)
        box.append(self.widget)

    def layout(self) -> None:
        """The cells for the channels: a linked pair shares one."""
        self.flow.clear()
        self.cells = []
        channels = self.channels
        i = 0
        while i < len(channels):
            port = channels[i].port
            pair = (
                port is not None
                and port.is_linked
                and port.is_left
                and i + 1 < len(channels)
                and channels[i + 1].port is port.partner
            )
            n = 2 if pair else 1
            meter = _Meter(n)
            self.flow.add(meter)
            self.cells.append(_Cell(meter, channels[i : i + n]))
            i += n


@Gtk.Template(string=blueprint("levels_panel"))
class LevelsPanel(Gtk.Box):
    __gtype_name__ = "LevelsPanel"

    banner: Adw.Banner = Gtk.Template.Child()
    groups: Gtk.Box = Gtk.Template.Child()

    def __init__(self, card_ui: CardUI) -> None:
        super().__init__()
        self.card = card = card_ui.card
        self.scope = card_ui.scope
        self._groups: list[_Group] = []
        self.show_unused = card.prefs.view(KEY_SHOW_UNUSED) == "true"
        elem = card.level_meter_elem
        assert elem is not None  # only created for cards with level meters

        if elem.meter_labels:
            self._build_labelled(elem.meter_labels)
        else:
            self._build_by_category(elem.count)

        folded = set((card.prefs.view(KEY_FOLDED) or "").split(","))
        for group in self._groups:
            expander = group.widget.expander
            expander.set_expanded(group.title not in folded)
            expander.connect("notify::expanded", lambda _e, _p: self._save_folded())

        self._layout()
        s = self.scope
        # linking pairs changes the cells, naming a pair its name
        s.connect(card, "stereo-changed", lambda _c: self._layout())
        s.connect(card, "routing-changed", lambda _c: self.refresh())
        s.connect(card, "port-visibility-changed", lambda _c, _pc, _src: self.refresh())
        for port in card.ports:
            s.connect(port, "name-changed", lambda _p: self.refresh())

    @staticmethod
    def _add(group: _Group, name: str, port: Port | None, level: Level) -> None:
        group.channels.append(_Channel(name, port, level))

    def _layout(self) -> None:
        for group in self._groups:
            group.layout()
        self.refresh()

    def _new_group(self, title: str) -> _Group:
        group = _Group(self.groups, title)
        self._groups.append(group)
        return group

    def _save_folded(self) -> None:
        folded = [g.title for g in self._groups if not g.widget.expander.get_expanded()]
        self.card.prefs.set_view(KEY_FOLDED, ",".join(folded))

    def _build_labelled(self, labels: list[str]) -> None:
        card = self.card
        current = None
        group = None
        for index, label in enumerate(labels):
            kind, _num = _split_label(label)
            if kind != current or group is None:
                current = kind
                group = self._new_group(kind)
            port: Port | None = None
            if label.startswith("Sink "):
                port = next(
                    (s for s in card.routing_snks if s.elem.name.startswith(label[5:] + " ")), None
                )
            elif label.startswith("Source "):
                port = next((s for s in card.routing_srcs if s.name == label[7:]), None)
            self._add(group, label, port, index)

    def _build_by_category(self, count: int) -> None:
        card = self.card
        # the sources have no meters of their own: they show the level at a
        # sink they are connected to (see core.features.levels)
        for src_pc, title in SRC_GROUPS:
            srcs = card.srcs_of(src_pc)
            if srcs:
                group = self._new_group(title)
                for src in srcs:
                    self._add(group, src.display_name, src, partial(card.src_level_db, src))

        # the meters of the sinks are ordered by category (PC): the index of
        # the first meter of each
        first = {}
        n_meters = 0
        for pc in range(PC_COUNT):
            first[pc] = n_meters
            n_meters += card.routing_out_count[pc]
        if n_meters != count:
            _log.warning("%d meters for the sinks, but the element has %d", n_meters, count)

        for pc in SNK_ORDER:
            n = min(card.routing_out_count[pc], count - first[pc])
            if n <= 0:
                continue
            group = self._new_group(PORT_CATEGORY_NAMES[pc] or "")
            snks = {s.elem.port_num: s for s in card.routing_snks if s.elem.port_category == pc}
            for j in range(n):
                snk = snks.get(j)
                self._add(group, snk.display_name if snk else str(j + 1), snk, first[pc] + j)

    # names and which meters are shown

    def refresh(self) -> None:
        hidden_unused = 0
        for group in self._groups:
            for cell in group.cells:
                shown, used = self._refresh_cell(cell)
                if shown and not used and not self.show_unused:
                    shown = False
                    hidden_unused += 1
                cell.meter.set_visible(shown)
            group.flow.queue_resize()
            group.widget.set_visible(any(m.get_visible() for m in group.flow.meters))
        self._fit_names()
        self._update_banner(hidden_unused)

    def _fit_names(self) -> None:
        """All cells as wide as the names of the shown ones need (within
        NAME_CHARS_MAX), the same in all groups."""
        meters = [cell.meter for group in self._groups for cell in group.cells]
        texts = [
            label.get_label()
            for meter in meters
            if meter.get_visible()
            for label in (meter.name, meter.source)
        ]
        chars = _chars_needed(texts)
        for meter in meters:
            meter.set_name_chars(chars)

    def _refresh_cell(self, cell: _Cell) -> tuple[bool, bool]:
        """Name the cell; (shown, used)."""
        card = self.card
        channels = cell.channels
        port = channels[0].port
        if port is None:
            cell.meter.set_names(channels[0].name, None)
            return True, True
        pair = len(channels) == 2
        # a linked pair is shown or hidden by its left channel
        shown = (port.left if port.is_linked and port.left else port).enabled
        name = port.pair_display_name if pair else port.display_name
        source = None
        used = True
        if isinstance(port, RoutingSnk):
            srcs = [
                card.src(c.port.elem.get_value())
                for c in channels
                if isinstance(c.port, RoutingSnk)
            ]
            src = next((s for s in srcs if s and s.id), None)
            used = src is not None
            if src:
                source = src.pair_display_name if pair and src.is_linked else src.display_name
            else:
                source = "Off"
        elif card.level_meter_elem and not card.level_meter_elem.meter_labels:
            # a source connected nowhere: nothing measures it
            used = any(c.port and c.port.level_index >= 0 for c in channels)
        cell.meter.set_names(name, source)
        return shown, used

    def _update_banner(self, hidden: int) -> None:
        if hidden:
            self.banner.set_title(f"{hidden} unused port{'' if hidden == 1 else 's'} hidden")
            self.banner.set_button_label("Show All")
        else:
            self.banner.set_title("Showing unused ports")
            self.banner.set_button_label("Hide Unused")
        self.banner.set_revealed(bool(hidden) or self.show_unused)

    @Gtk.Template.Callback()
    def _on_collapse_all(self, *_args: object) -> None:
        for group in self._groups:
            group.widget.expander.set_expanded(False)

    @Gtk.Template.Callback()
    def _on_expand_all(self, *_args: object) -> None:
        for group in self._groups:
            group.widget.expander.set_expanded(True)

    @Gtk.Template.Callback()
    def _on_toggle_unused(self, *_args: object) -> None:
        self.show_unused = not self.show_unused
        self.card.prefs.set_view(KEY_SHOW_UNUSED, "true" if self.show_unused else "false")
        self.refresh()

    def update(self) -> None:
        now = time.monotonic()
        levels = self.card.routing_levels
        for group in self._groups:
            for cell in group.cells:
                for i, channel in enumerate(cell.channels):
                    level = channel.level
                    if isinstance(level, int):
                        db = levels[level] if level < len(levels) else NO_SIGNAL_DB
                    else:
                        db = level()
                    cell.meter.set_level(i, db, now)

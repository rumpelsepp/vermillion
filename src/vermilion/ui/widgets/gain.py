# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gain/volume control: a Gtk.Scale with an optional Gtk.LevelBar and
an optional pan control; a double-click on a value opens a popover to
type one."""

import math
from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import Gdk, GLib, Gtk

from vermilion.core import controls, db, pan
from vermilion.core.util import c_round
from vermilion.ui.resources import blueprint

if TYPE_CHECKING:
    from vermilion.core.card import Elem
    from vermilion.core.scope import Scope

# level bar range and colour breakpoints (dB)
LEVEL_MIN_DB = -60.0
LEVEL_OFFSETS = (("low", -12.0), ("high", -3.0), ("full", 0.0))

# Gtk.LevelBar values can't be negative: it shows dB above LEVEL_MIN_DB

# fader law (of mixing desks and DAWs, e.g. Ardour): the position (0..1)
# is ((dB - max + FADER_DB_RANGE) / FADER_DB_RANGE) ** FADER_EXPONENT, so
# that much of the travel is around 0 dB and little in the quiet part
FADER_DB_RANGE = 198.0
FADER_EXPONENT = 8
FADER_STEPS = 1000
# dB per step of the mouse wheel (with Shift: fine)
WHEEL_DB, WHEEL_DB_FINE = 0.5, 0.1


def setup_level_bar(bar: Gtk.LevelBar) -> None:
    """Level bar for dB values, with colour breakpoints."""
    bar.set_max_value(-LEVEL_MIN_DB)
    for name, level in LEVEL_OFFSETS:
        bar.add_offset_value(name, level - LEVEL_MIN_DB)


def set_level_db(bar: Gtk.LevelBar, level_db: float | None) -> None:
    if level_db is None or math.isnan(level_db):
        level_db = LEVEL_MIN_DB
    bar.set_value(max(0.0, min(0.0, level_db) - LEVEL_MIN_DB))


def format_db(value: float, fine: bool, zero_is_off: bool, min_db: float) -> str:
    """Format a dB value like "−10dB", "+2.5" or "Off"."""
    if zero_is_off and value <= min_db:
        return "Off"
    if fine:
        value = round(value * 10) / 10
    sign = "−" if value < 0 else "+" if value > 0 else ""
    if fine:
        return f"{sign}{abs(value):.1f}"
    return f"{sign}{abs(value):.0f}dB"


def _on_double_press(widget: Gtk.Widget, action: Callable[[], None]) -> None:
    """Run action on a double-click on widget. A Gtk.GestureClick doesn't
    work on a scale: the scale claims the clicks, which cancels the
    gesture and so resets its count; this controller only watches.

    The action runs when the second click is released: until then the
    scale drags the slider, and the slightest movement of the mouse would
    move it away from where the action put it."""
    settings = Gtk.Settings.get_default()
    last: list[float] = [-1e9, 0.0, 0.0]
    pending = [False]

    def run() -> bool:
        action()
        return GLib.SOURCE_REMOVE

    def event(controller: Gtk.EventControllerLegacy, _event: object) -> bool:
        # PyGObject passes None as the event: it's the current one
        ev = controller.get_current_event()
        if not isinstance(ev, Gdk.ButtonEvent) or ev.get_button() != Gdk.BUTTON_PRIMARY:
            return False
        if ev.get_event_type() == Gdk.EventType.BUTTON_RELEASE:
            if pending[0]:
                pending[0] = False
                # after the scale has handled the release
                GLib.idle_add(run)
            return False
        if ev.get_event_type() != Gdk.EventType.BUTTON_PRESS:
            return False
        _ok, x, y = ev.get_position()
        time = ev.get_time()
        interval = settings.props.gtk_double_click_time if settings else 400
        distance = settings.props.gtk_double_click_distance if settings else 5
        t, lx, ly = last
        if time - t <= interval and abs(x - lx) <= distance and abs(y - ly) <= distance:
            last[0] = -1e9
            pending[0] = True
        else:
            last[:] = [time, x, y]
        return False

    controller = Gtk.EventControllerLegacy(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    controller.connect("event", event)
    widget.add_controller(controller)


@Gtk.Template(string=blueprint("value_popover"))
class ValuePopover(Gtk.Popover):
    """Typing a value, like the rename popover of Nautilus: parse turns
    the text into one (None if invalid), on_set takes it. An invalid one
    keeps the popover open and marks the entry and the hint."""

    __gtype_name__ = "ValuePopover"

    heading: Gtk.Label = Gtk.Template.Child()
    entry: Gtk.Entry = Gtk.Template.Child()
    hint: Gtk.Label = Gtk.Template.Child()

    def __init__(
        self,
        heading: str,
        hint: str,
        parse: Callable[[str], float | None],
        on_set: Callable[[float], None],
    ) -> None:
        super().__init__()
        self.heading.set_label(heading)
        self.hint.set_label(hint)
        self._parse = parse
        self._set = on_set

    def open(self, text: str) -> None:
        self.entry.set_text(text)
        self._show_error(False)
        self.popup()
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    @Gtk.Template.Callback()
    def _on_set(self, *_args: object) -> None:
        value = self._parse(self.entry.get_text())
        if value is None:
            self._show_error(True)
            self.entry.grab_focus()
            return
        self._set(value)
        self.popdown()

    def _show_error(self, show: bool) -> None:
        for widget in (self.entry, self.hint):
            if show:
                widget.add_css_class("error")
            else:
                widget.remove_css_class("error")
        if show:
            self.hint.remove_css_class("dim-label")
        else:
            self.hint.add_css_class("dim-label")


@Gtk.Template(string=blueprint("gain_control"))
class GainControl(Gtk.Box):
    """Controls one element, or several in sync (stereo).

    With pan, the two elements are the left and right gains of a stereo
    mixer cell: the fader sets the level and the pan control their ratio
    (see core.pan).
    """

    __gtype_name__ = "GainControl"

    fader: Gtk.Box = Gtk.Template.Child()
    scale: Gtk.Scale = Gtk.Template.Child()
    adjustment: Gtk.Adjustment = Gtk.Template.Child()
    level: Gtk.LevelBar = Gtk.Template.Child()
    value_icon: Gtk.Image = Gtk.Template.Child()
    value_label: Gtk.Label = Gtk.Template.Child()
    pan_box: Gtk.Box = Gtk.Template.Child()
    pan_value: Gtk.Label = Gtk.Template.Child()
    pan_scale: Gtk.Scale = Gtk.Template.Child()
    pan_adjustment: Gtk.Adjustment = Gtk.Template.Child()

    def __init__(
        self,
        scope: Scope,
        elems: Elem | list[Elem],
        zero_is_off: bool = True,
        show_level: bool = False,
        can_control: bool = True,
        height: int | None = None,
        pan_label: str | None = None,
        horizontal: bool = False,
        fader_law: bool = False,
    ) -> None:
        """pan_label ("Pan", "Balance") enables the pan control for a
        pair of elements [left, right]. horizontal: a horizontal fader with
        the value at its end (e.g. in a list row); height is then the
        length of the fader. fader_law: the fader of a mixing desk, with
        more travel around 0 dB, without stopping at it, and the mouse
        wheel in steps of dB."""
        super().__init__()
        if horizontal:
            self._make_horizontal(height or 180)
        elif height:
            self.scale.set_size_request(-1, height)
        if not isinstance(elems, (list, tuple)):
            elems = [elems]
        self.elems = list(elems)
        self.elem = elem = self.elems[0]
        self.pan_label = pan_label if len(self.elems) == 2 else None
        self.pan = 0.0
        self._pan_idle = 0
        self._pan_deferred = False
        self.zero_is_off = zero_is_off
        self.linear = elem.is_linear
        self._syncing = False
        self.min_db = c_round(elem.min_cdb / 100.0)
        self.max_db = c_round(elem.max_cdb / 100.0)

        # direct monitor mirroring only applies to single (mono) controls
        self._dm = controls.direct_monitor_mix_elems(elem) if len(self.elems) == 1 else None

        adj = self.adjustment
        self.law = fader_law and elem.db is not None
        if self.law:
            span = elem.max_val - elem.min_val
            self.fine = bool(span) and (elem.max_cdb - elem.min_cdb) / 100.0 / span <= 0.5
            adj.configure(0, 0, FADER_STEPS, 1, 10, 0)
            self._zero_pos = self._db_to_pos(0.0)
            wheel = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
            wheel.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            wheel.connect("scroll", self._on_wheel)
            self.scale.add_controller(wheel)
        elif self.linear:
            # linear-amplitude controls are handled in dB space
            self.fine = True
            lower = max(self.min_db, -80.0)
            adj.configure(0, lower, self.max_db, 0.5, 3, 0)
            self._zero_pos = 0.0
        else:
            span = elem.max_val - elem.min_val
            step_db = (elem.max_cdb - elem.min_cdb) / 100.0 / span if span else 1
            self.fine = step_db <= 0.5
            adj.configure(
                elem.min_val,
                elem.min_val,
                elem.max_val,
                1,
                max(1, round(3 / step_db)) if step_db else 1,
                0,
            )
            self._zero_pos = (
                elem.min_val + (0 - elem.min_cdb / 100.0) / step_db if step_db else elem.min_val
            )

        # a mark stops the fader: not with the fader law
        if not self.law and adj.get_lower() <= self._zero_pos <= adj.get_upper():
            side = Gtk.PositionType.TOP if horizontal else Gtk.PositionType.LEFT
            self.scale.add_mark(self._zero_pos, side, None)

        if not can_control:
            # no keyboard focus (e.g. the cells of the mixer); the value can
            # still be clicked and typed
            self.scale.set_can_focus(False)

        if show_level:
            self.level.set_visible(True)
            setup_level_bar(self.level)

        self._handler = adj.connect("value-changed", self._on_value_changed)
        adj.connect("value-changed", lambda _adj: self._show_value())

        # the popovers to type a value, by the label they belong to
        self._popovers: dict[Gtk.Label, ValuePopover] = {}
        self.connect("destroy", lambda _w: self._drop_popovers())

        if self.pan_label:
            self.pan_box.set_visible(True)
            self.pan_scale.add_mark(0.0, Gtk.PositionType.TOP, None)
            self._pan_handler = self.pan_adjustment.connect("value-changed", self._on_pan_changed)
            # double-click centres
            _on_double_press(self.pan_scale, lambda: self.pan_adjustment.set_value(0.0))
            self._on_double_click(self.pan_value, self.edit_pan)

        # a double-click on the value opens a popover to type one
        self._on_double_click(self.value_label, self.edit_level)

        # double-click: 0 dB for a fader (mixer), otherwise it toggles
        # between -inf and 0 dB
        _on_double_press(self.scale, self._on_double_press)

        for e in self.elems:
            scope.watch(e, self._update)
        self._update(elem)
        self._show_value()
        self._pan_deferred = True

    def _make_horizontal(self, length: int) -> None:
        self.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.set_spacing(6)
        self.set_valign(Gtk.Align.CENTER)
        self.set_vexpand(False)
        self.fader.set_orientation(Gtk.Orientation.VERTICAL)
        self.fader.set_vexpand(False)
        self.fader.set_valign(Gtk.Align.CENTER)
        for widget in (self.scale, self.level):
            widget.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.scale.set_inverted(False)
        self.scale.set_vexpand(False)
        self.scale.set_size_request(length, -1)
        self.level.set_inverted(False)
        self.level.set_size_request(-1, 5)
        self.value_label.set_valign(Gtk.Align.CENTER)
        self.value_label.set_width_chars(6)
        self.value_label.set_max_width_chars(6)
        self.value_label.set_xalign(1.0)

    # conversion between adjustment position and element value

    def _db_to_pos(self, level: float) -> float:
        norm = (level - self.max_db + FADER_DB_RANGE) / FADER_DB_RANGE
        return float(max(0.0, min(1.0, norm)) ** FADER_EXPONENT) * FADER_STEPS

    def _pos_to_db(self, pos: float) -> float:
        norm = float((pos / FADER_STEPS) ** (1 / FADER_EXPONENT))
        return self.max_db - FADER_DB_RANGE + FADER_DB_RANGE * norm

    def _on_wheel(self, controller: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        state = controller.get_current_event_state()
        step = WHEEL_DB_FINE if state & Gdk.ModifierType.SHIFT_MASK else WHEEL_DB
        value = self._pos_to_value(self.adjustment.get_value())
        current = self.min_db if value <= self.elem.min_val else self.elem.value_to_db(value)
        self.set_db(current - dy * step if dy else current)
        return True

    def _pos_to_value(self, pos: float) -> int:
        if self.law:
            if pos <= 0:
                return self.elem.min_val
            return self.elem.db_to_value(max(self.min_db, self._pos_to_db(pos)))
        if self.linear:
            if pos <= self.adjustment.get_lower():
                return self.elem.min_val
            return self.elem.db_to_value(pos)
        return round(pos)

    def _value_to_pos(self, value: int) -> float:
        if self.law:
            if value <= self.elem.min_val:
                return 0.0
            return self._db_to_pos(self.elem.value_to_db(value))
        if self.linear:
            return self.elem.value_to_db(value)
        return value

    def _on_value_changed(self, adj: Gtk.Adjustment) -> None:
        value = self._pos_to_value(adj.get_value())
        if self.pan_label:
            self._write_panned(value)
            return
        self._syncing = True
        try:
            if len(self.elems) > 1:
                for e in self.elems:
                    e.set_value(value)
            else:
                controls.set_gain(self.elem, value, self._dm)
        finally:
            self._syncing = False

    def _on_double_press(self) -> None:
        adj = self.adjustment
        if not self.law and adj.get_value() != adj.get_lower():
            adj.set_value(adj.get_lower())
        else:
            adj.set_value(self._zero_pos)

    # the value: shown below the fader, can be typed

    def _show_value(self) -> None:
        value = self._pos_to_value(self.adjustment.get_value())
        off = self.zero_is_off and value <= self.elem.min_val
        # greyed out while off (it can still be moved)
        if off:
            self.add_css_class("off")
        else:
            self.remove_css_class("off")
        if off:
            # also for linear controls, whose minimum is a "mute" dB value
            self.value_label.set_text("Off")
            self.value_icon.set_from_icon_name("audio-volume-muted-symbolic")
            return
        level = self.elem.value_to_db(value)
        self.value_label.set_text(format_db(level, self.fine, self.zero_is_off, self.min_db))
        volume = "low" if level < -20 else "medium" if level < -6 else "high"
        self.value_icon.set_from_icon_name(f"audio-volume-{volume}-symbolic")

    @staticmethod
    def _on_double_click(label: Gtk.Label, edit: Callable[[], None]) -> None:
        def pressed(_gesture: Gtk.GestureClick, n_press: int, _x: float, _y: float) -> None:
            if n_press == 2 and label.is_sensitive() and label.get_mapped():
                edit()

        click = Gtk.GestureClick()
        click.connect("pressed", pressed)
        label.add_controller(click)

    def _edit(
        self,
        label: Gtk.Label,
        heading: str,
        hint: str,
        parse: Callable[[str], float | None],
        on_set: Callable[[float], None],
    ) -> None:
        popover = self._popovers.get(label)
        if not popover:
            popover = self._popovers[label] = ValuePopover(heading, hint, parse, on_set)
            popover.set_parent(label)
        popover.open(label.get_text())

    def _drop_popovers(self) -> None:
        # a popover isn't removed with its parent
        for popover in self._popovers.values():
            popover.unparent()
        self._popovers = {}

    def edit_level(self) -> None:
        """Open the popover to type a level."""
        self._edit(
            self.value_label,
            "Level in dB",
            "Type off to switch it off.",
            db.parse_db,
            self.set_db,
        )

    def edit_pan(self) -> None:
        """Open the popover to type a pan position."""
        assert self.pan_label
        self._edit(
            self.pan_value,
            self.pan_label,
            "C for the centre, L or R and a percentage (or −100 … 100).",
            pan.parse_pan,
            self.pan_adjustment.set_value,
        )

    def set_db(self, level: float) -> None:
        """Set the gain (or, with pan, the level) to a dB value, limited to
        the range of the control; -inf for the minimum."""
        adj = self.adjustment
        if level == -math.inf or level < self.min_db:
            pos = adj.get_lower()
        elif self.law:
            pos = self._db_to_pos(min(level, self.max_db))
        elif self.linear:
            pos = level
        else:
            pos = self.elem.db_to_value(min(level, self.max_db))
        adj.set_value(max(adj.get_lower(), min(adj.get_upper(), pos)))

    # pan

    @staticmethod
    def _elem_db(elem: Elem, value: int) -> float:
        return pan.NEG_INF if value <= elem.min_val else elem.gain_db(value)

    @staticmethod
    def _db_value(elem: Elem, level_db: float) -> int:
        if level_db == pan.NEG_INF or level_db < elem.min_cdb / 100.0:
            return elem.min_val
        return elem.db_to_value(level_db)

    def _write_panned(self, value: int) -> None:
        """Set the louder side to value and the other one by the pan."""
        level = self._elem_db(self.elem, value)
        sides = pan.split(level, self.pan)
        self._syncing = True
        try:
            for e, side_db in zip(self.elems, sides, strict=True):
                e.set_value(value if side_db == level else self._db_value(e, side_db))
        finally:
            self._syncing = False

    def _on_pan_changed(self, adj: Gtk.Adjustment) -> None:
        self.pan = adj.get_value()
        self._update_pan_tooltip()
        self._write_panned(self._pos_to_value(self.adjustment.get_value()))

    def _update_pan_tooltip(self) -> None:
        text = pan.format_pan(self.pan)
        self.pan_value.set_label(text)
        self.pan_scale.set_tooltip_text(f"{self.pan_label}: {text}")

    def _update_panned(self) -> None:
        left, right = self.elems
        values = [left.get_value(), right.get_value()]
        writable = left.writable()
        self.scale.set_sensitive(writable)
        self.value_label.set_sensitive(writable)
        self.pan_box.set_sensitive(writable)
        with self.adjustment.handler_block(self._handler):
            self.adjustment.set_value(self._value_to_pos(max(values)))
        # the two gains change one after the other (e.g. when muting),
        # so the pan position is taken once both have arrived
        if self._pan_deferred:
            if not self._pan_idle:
                self._pan_idle = GLib.idle_add(self._update_pan_position)
        else:
            self._update_pan_position()

    def _update_pan_position(self) -> bool:
        self._pan_idle = 0
        left, right = self.elems
        _, position = pan.combine(
            self._elem_db(left, left.get_value()), self._elem_db(right, right.get_value())
        )
        # silent: keep the pan position
        if position is not None:
            self.pan = position
            with self.pan_adjustment.handler_block(self._pan_handler):
                self.pan_adjustment.set_value(position)
        self._update_pan_tooltip()
        return GLib.SOURCE_REMOVE

    def _update(self, elem: Elem) -> None:
        if self._syncing:
            return
        if self.pan_label:
            self._update_panned()
            return

        self.scale.set_sensitive(elem.writable())
        self.value_label.set_sensitive(elem.writable())
        value = elem.get_value()

        # stereo: keep the other elements in sync with this one
        if len(self.elems) > 1:
            self._syncing = True
            for other in self.elems:
                if other is not elem and other.get_value() != value:
                    other.set_value(value)
            self._syncing = False

        with self.adjustment.handler_block(self._handler):
            self.adjustment.set_value(self._value_to_pos(value))

    def gain_db(self) -> float:
        """Current gain in dB (for post-gain level display); with pan, the
        gain of the louder side."""
        return max(e.gain_db(e.get_value()) for e in self.elems[: 2 if self.pan_label else 1])

    def set_level(self, level_db: float | None) -> None:
        set_level_db(self.level, level_db)

    def set_compact(self, compact: bool) -> None:
        """Only the values, without the fader, level and pan slider (e.g. a
        folded row of the mixer), the level with a speaker icon; a
        double-click on a value still types one."""
        self.fader.set_visible(not compact)
        self.value_icon.set_visible(compact)
        self.pan_scale.set_visible(not compact)
        self.set_vexpand(not compact)

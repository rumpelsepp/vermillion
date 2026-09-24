# SPDX-FileCopyrightText: 2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Graphs for the DSP window: filter response and compressor curve.

GTK has no widgets for these, so they are drawn with cairo on a
Gtk.DrawingArea; interaction uses the standard event controllers.
"""

import math
from collections.abc import Callable, Iterator
from typing import ClassVar

import cairo
from gi.repository import Gtk

from vermilion.core import biquad
from vermilion.core.biquad import DB_RANGE_NARROW, GAIN_DB_LIMIT
from vermilion.core.features import dsp
from vermilion.core.signals import SignalSpec, signal
from vermilion.core.util import clamp


def _fg(cr: cairo.Context[cairo.Surface], widget: Gtk.Widget, alpha: float = 1.0) -> None:
    """Use the widget's foreground (text) colour, so that the graphs
    follow the light or dark style."""
    c = widget.get_color()
    cr.set_source_rgba(c.red, c.green, c.blue, c.alpha * alpha)


FREQ_MIN, FREQ_MAX = 20.0, 20000.0
Q_MIN, Q_MAX = 0.1, 10.0

BAND_COLOURS = [
    (0.4, 0.7, 0.9),
    (0.4, 0.8, 0.4),
    (0.9, 0.9, 0.3),
    (0.9, 0.6, 0.3),
    (0.9, 0.4, 0.4),
    (0.7, 0.4, 0.9),
    (0.4, 0.9, 0.9),
    (0.9, 0.4, 0.7),
]

_GRID_FREQS = [
    20,
    30,
    40,
    50,
    60,
    70,
    80,
    90,
    100,
    200,
    300,
    400,
    500,
    600,
    700,
    800,
    900,
    1000,
    2000,
    3000,
    4000,
    5000,
    6000,
    7000,
    8000,
    9000,
    10000,
    20000,
]
_FREQ_LABELS = [
    (20, "20"),
    (50, "50"),
    (100, "100"),
    (200, "200"),
    (500, "500"),
    (1000, "1k"),
    (2000, "2k"),
    (5000, "5k"),
    (10000, "10k"),
    (20000, "20k"),
]


def _freqs() -> Iterator[float]:
    f = FREQ_MIN
    while f <= FREQ_MAX:
        yield f
        f *= 1.02


class _Area:
    """Coordinate mapping for the filter graph."""

    def __init__(self, width: float, height: float, db_range: float) -> None:
        self.left, self.right = 28, width - 12
        self.top, self.bottom = 3, height - 15
        self.width = self.right - self.left
        self.height = self.bottom - self.top
        self.db_min, self.db_max = -db_range, db_range

    def freq_x(self, f: float) -> float:
        lo, hi = math.log10(FREQ_MIN), math.log10(FREQ_MAX)
        return self.left + (math.log10(f) - lo) / (hi - lo) * self.width

    def x_freq(self, x: float) -> float:
        lo, hi = math.log10(FREQ_MIN), math.log10(FREQ_MAX)
        return 10 ** (lo + (x - self.left) / self.width * (hi - lo))

    def db_y(self, db: float) -> float:
        return self.bottom - (db - self.db_min) / (self.db_max - self.db_min) * self.height

    def y_db(self, y: float) -> float:
        return self.db_min + (self.bottom - y) / self.height * (self.db_max - self.db_min)

    def q_y(self, q: float) -> float:
        lo, hi = math.log10(Q_MIN), math.log10(Q_MAX)
        return self.bottom - (math.log10(q) - lo) / (hi - lo) * self.height

    def y_q(self, y: float) -> float:
        lo, hi = math.log10(Q_MIN), math.log10(Q_MAX)
        return 10 ** (lo + (self.bottom - y) / self.height * (hi - lo))

    def handle_pos(self, p: biquad.Params) -> tuple[float, float]:
        y = self.db_y(p.gain_db) if biquad.uses_gain(p.type) else self.q_y(p.q)
        return self.freq_x(p.freq), y


class FilterResponse(Gtk.DrawingArea):
    """Frequency response of a set of biquad bands with draggable handles.

    Emits "filter-changed"(band, params) when a handle is dragged or
    scrolled, and "highlight-changed"(band) on hover (-1 for none).
    """

    __gsignals__: ClassVar[dict[str, SignalSpec]] = {
        "filter-changed": signal(int, object),
        "highlight-changed": signal(int),
    }

    def __init__(self, num_bands: int) -> None:
        super().__init__()
        self.set_size_request(200, 150)
        self.set_content_width(400)
        self.set_content_height(300)
        self.set_hexpand(True)
        self.num_bands = num_bands
        self.bands = [
            biquad.Params(biquad.FilterType.PEAKING, 1000, 1.0, 0) for _ in range(num_bands)
        ]
        self.coeffs = [biquad.calculate(p, dsp.SAMPLE_RATE) for p in self.bands]
        self.band_enabled = [True] * num_bands
        self.dsp_enabled = True
        self.db_range = GAIN_DB_LIMIT
        self.highlight = -1
        self._hover = -1
        self._hover_toggle = False
        self._drag_band = -1
        self._drag_offset = (0.0, 0.0)

        self.set_draw_func(self._draw)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", lambda *_: setattr(self, "_drag_band", -1))
        self.add_controller(drag)

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

    def _area(self) -> _Area:
        return _Area(self.get_width(), self.get_height(), self.db_range)

    # API

    def set_filter(self, band: int, params: biquad.Params) -> None:
        if 0 <= band < self.num_bands:
            self.bands[band] = params.copy()
            self.coeffs[band] = biquad.calculate(params, dsp.SAMPLE_RATE)
            self.queue_draw()

    def set_band_enabled(self, band: int, enabled: bool) -> None:
        if 0 <= band < self.num_bands and self.band_enabled[band] != enabled:
            self.band_enabled[band] = enabled
            self.queue_draw()

    def set_dsp_enabled(self, enabled: bool) -> None:
        if self.dsp_enabled != enabled:
            self.dsp_enabled = enabled
            self.queue_draw()

    def set_highlight(self, band: int) -> None:
        if self.highlight != band:
            self.highlight = band
            self.queue_draw()

    def set_db_range(self, new_range: float) -> None:
        self.db_range = new_range
        for i, p in enumerate(self.bands):
            if abs(p.gain_db) > new_range:
                p.gain_db = clamp(p.gain_db, -new_range, new_range)
                self.coeffs[i] = biquad.calculate(p, dsp.SAMPLE_RATE)
                self.emit("filter-changed", i, p)
        self.queue_draw()

    def auto_range(self) -> None:
        narrow = all(abs(p.gain_db) <= DB_RANGE_NARROW for p in self.bands)
        self.set_db_range(DB_RANGE_NARROW if narrow else GAIN_DB_LIMIT)

    # interaction

    def _band_at(self, x: float, y: float) -> int:
        area = self._area()
        best, best_d = -1, 12.0 * 12.0
        for i, p in enumerate(self.bands):
            hx, hy = area.handle_pos(p)
            d = (x - hx) ** 2 + (y - hy) ** 2
            if d < best_d:
                best, best_d = i, d
        return best

    def _in_toggle(self, area: _Area, x: float, y: float) -> bool:
        return x >= area.right - 30 and y <= area.top + 16

    def _on_motion(self, _ctrl: Gtk.EventController, x: float, y: float) -> None:
        area = self._area()
        in_toggle = self._in_toggle(area, x, y)
        band = self._band_at(x, y)
        changed = in_toggle != self._hover_toggle
        self._hover_toggle = in_toggle
        if band != self._hover:
            self._hover = self.highlight = band
            self.emit("highlight-changed", band)
            changed = True
        if changed:
            self.queue_draw()

    def _on_leave(self, _ctrl: Gtk.EventController) -> None:
        self._hover_toggle = False
        if self._hover != -1:
            self._hover = self.highlight = -1
            self.emit("highlight-changed", -1)
        self.queue_draw()

    def _on_drag_begin(self, gesture: Gtk.GestureDrag, x: float, y: float) -> None:
        area = self._area()
        band = self._band_at(x, y)
        if band >= 0:
            self._drag_band = self.highlight = band
            hx, hy = area.handle_pos(self.bands[band])
            self._drag_offset = (x - hx, y - hy)
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        elif self._in_toggle(area, x, y):
            self.set_db_range(DB_RANGE_NARROW if self.db_range == GAIN_DB_LIMIT else GAIN_DB_LIMIT)
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _on_drag_update(self, gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        band = self._drag_band
        if band < 0:
            return
        _ok, sx, sy = gesture.get_start_point()
        x = sx + dx - self._drag_offset[0]
        y = sy + dy - self._drag_offset[1]
        area = self._area()
        p = self.bands[band]
        p.freq = clamp(area.x_freq(x), FREQ_MIN, FREQ_MAX)
        if biquad.uses_gain(p.type):
            p.gain_db = clamp(area.y_db(y), area.db_min, area.db_max)
        else:
            p.q = clamp(area.y_q(y), Q_MIN, Q_MAX)
        self.coeffs[band] = biquad.calculate(p, dsp.SAMPLE_RATE)
        self.emit("filter-changed", band, p)
        self.queue_draw()

    def _on_scroll(self, _ctrl: Gtk.EventController, _dx: float, dy: float) -> bool:
        band = self._hover
        if band < 0 or not biquad.uses_gain(self.bands[band].type):
            return False
        p = self.bands[band]
        p.q = clamp(p.q * (0.9 if dy > 0 else 1.1), Q_MIN, Q_MAX)
        self.coeffs[band] = biquad.calculate(p, dsp.SAMPLE_RATE)
        self.emit("filter-changed", band, p)
        self.queue_draw()
        return True

    # drawing

    def _curve(
        self, cr: cairo.Context[cairo.Surface], area: _Area, fn: Callable[[float], float]
    ) -> None:
        first = True
        for f in _freqs():
            x, y = area.freq_x(f), area.db_y(fn(f))
            if first:
                cr.move_to(x, y)
                first = False
            else:
                cr.line_to(x, y)

    def _draw_band(
        self, cr: cairo.Context[cairo.Surface], area: _Area, i: int, alpha: float, dashed: bool
    ) -> None:
        r, g, b = BAND_COLOURS[i % 8]
        c = self.coeffs[i]

        def resp(f: float) -> float:
            return biquad.response_db(c, f, dsp.SAMPLE_RATE)

        cr.save()
        y0 = area.db_y(0)
        cr.move_to(area.freq_x(FREQ_MIN), y0)
        for f in _freqs():
            cr.line_to(area.freq_x(f), area.db_y(resp(f)))
        cr.line_to(area.freq_x(FREQ_MAX), y0)
        cr.close_path()
        cr.set_source_rgba(r, g, b, alpha * 0.3)
        cr.fill()

        self._curve(cr, area, resp)
        cr.set_source_rgba(r, g, b, alpha)
        cr.set_line_width(1.5)
        if dashed:
            cr.set_dash([4.0, 4.0])
        cr.stroke()
        cr.restore()

    def _draw_handle(
        self,
        cr: cairo.Context[cairo.Surface],
        area: _Area,
        i: int,
        alpha: float,
        highlighted: bool,
        enabled: bool,
    ) -> None:
        r, g, b = BAND_COLOURS[i % 8]
        p = self.bands[i]
        x, y = area.handle_pos(p)
        radius = 12 if highlighted else 10

        cr.save()
        cr.new_path()
        if biquad.uses_gain(p.type) and p.type != biquad.FilterType.GAIN:
            ratio = 2.0 ** (0.5 / p.q)
            x_lo = area.freq_x(max(p.freq / ratio, FREQ_MIN)) - radius
            x_hi = area.freq_x(min(p.freq * ratio, FREQ_MAX)) + radius
            cr.set_source_rgba(r, g, b, alpha * 0.8)
            cr.set_line_width(2 if highlighted else 1.5)
            cr.move_to(x_lo, y)
            cr.line_to(x_hi, y)
            tick = 4 if highlighted else 3
            for xx in (x_lo, x_hi):
                cr.move_to(xx, y - tick)
                cr.line_to(xx, y + tick)
            cr.stroke()

        cr.arc(x, y, radius, 0, 2 * math.pi)
        cr.set_source_rgba(0.2, 0.2, 0.2, alpha)
        cr.fill_preserve()
        cr.set_source_rgba(r, g, b, alpha)
        cr.set_line_width(1.5)
        if not enabled:
            cr.set_dash([3.0, 3.0])
        cr.stroke()
        cr.set_dash([])

        cr.select_font_face("sans-serif", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        cr.set_font_size(11 if highlighted else 10)
        text = str(i + 1)
        ext = cr.text_extents(text)
        cr.move_to(x - ext.width / 2 - ext.x_bearing, y - ext.height / 2 - ext.y_bearing)
        cr.show_text(text)
        cr.restore()

    def _draw(
        self, _area: Gtk.DrawingArea, cr: cairo.Context[cairo.Surface], width: int, height: int
    ) -> None:
        area = _Area(width, height, self.db_range)

        _fg(cr, self, 0.05)
        cr.rectangle(area.left, area.top, area.width, area.height)
        cr.fill()

        _fg(cr, self, 0.15)
        cr.set_line_width(0.5)
        db = area.db_min
        while db <= area.db_max:
            y = area.db_y(db)
            cr.move_to(area.left, y)
            cr.line_to(area.right, y)
            db += 6
        for f in _GRID_FREQS:
            x = area.freq_x(f)
            cr.move_to(x, area.top)
            cr.line_to(x, area.bottom)
        cr.stroke()

        _fg(cr, self, 0.3)
        cr.set_line_width(1)
        cr.move_to(area.left, area.db_y(0))
        cr.line_to(area.right, area.db_y(0))
        cr.stroke()

        _fg(cr, self, 0.6)
        cr.select_font_face("sans-serif", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        cr.set_font_size(8)
        db = area.db_min
        while db <= area.db_max:
            label = f"{db:+.0f}"
            ext = cr.text_extents(label)
            cr.move_to(area.left - ext.width - 3, area.db_y(db) + ext.height / 2)
            cr.show_text(label)
            db += 6
        for f, label in _FREQ_LABELS:
            ext = cr.text_extents(label)
            cr.move_to(area.freq_x(f) - ext.width / 2, area.bottom + ext.height + 3)
            cr.show_text(label)

        cr.save()
        cr.rectangle(area.left, area.top, area.width, area.height)
        cr.clip()

        def on(i: int) -> bool:
            return self.band_enabled[i] and self.dsp_enabled

        for i in range(self.num_bands):
            if i != self.highlight:
                self._draw_band(cr, area, i, 0.5 if on(i) else 0.3, not on(i))

        # combined response
        cr.save()
        cr.set_line_width(2)
        if self.dsp_enabled:
            _fg(cr, self)
        else:
            _fg(cr, self, 0.5)
            cr.set_dash([6.0, 4.0])
        enabled = [c for c, e in zip(self.coeffs, self.band_enabled) if e]
        self._curve(
            cr, area, lambda f: sum(biquad.response_db(c, f, dsp.SAMPLE_RATE) for c in enabled)
        )
        cr.stroke()
        cr.restore()

        h = self.highlight
        if 0 <= h < self.num_bands:
            self._draw_band(cr, area, h, 1.0 if on(h) else 0.6, not on(h))

        order = [i for i in range(self.num_bands) if i != h]
        if h < 0:
            order.reverse()  # band 1 on top
        for i in order:
            self._draw_handle(cr, area, i, 0.7 if on(i) else 0.4, False, on(i))
        if 0 <= h < self.num_bands:
            self._draw_handle(cr, area, h, 1.0 if on(h) else 0.6, True, on(h))

        cr.restore()

        # range toggle indicator
        _fg(cr, self, 0.9 if self._hover_toggle else 0.4)
        cr.set_font_size(9)
        label = f"±{int(self.db_range)}"
        ext = cr.text_extents(label)
        cr.move_to(area.right - ext.width - 4, area.top + ext.height + 4)
        cr.show_text(label)


class CompressorCurve(Gtk.DrawingArea):
    """Static compressor transfer curve with the current level as a dot."""

    SIZE = 150
    MARGIN = 18
    PAD = 3
    DB_MIN, DB_MAX = -60.0, 0.0

    def __init__(self) -> None:
        super().__init__()
        self.set_content_width(self.SIZE)
        self.set_content_height(self.SIZE)
        self.threshold = -22
        self.ratio = 8  # ratio * 2
        self.knee = 3
        self.makeup = 5
        self.dsp_enabled = True
        self.input_db = self.output_db = -80.0
        self.set_draw_func(self._draw)

    def set_param(self, name: str, value: float) -> None:
        if getattr(self, name) != value:
            setattr(self, name, value)
            self.queue_draw()

    def set_dsp_enabled(self, enabled: bool) -> None:
        self.set_param("dsp_enabled", enabled)

    def set_levels(self, input_db: float, output_db: float) -> None:
        self.input_db, self.output_db = input_db, output_db
        self.queue_draw()

    def _x(self, db: float) -> float:
        left, right = self.MARGIN, self.SIZE - self.PAD
        return left + (db - self.DB_MIN) / (self.DB_MAX - self.DB_MIN) * (right - left)

    def _y(self, db: float) -> float:
        top, bottom = self.PAD, self.SIZE - self.MARGIN
        return bottom - (db - self.DB_MIN) / (self.DB_MAX - self.DB_MIN) * (bottom - top)

    def _out(self, input_db: float) -> float:
        return dsp.compressor_output(self.threshold, self.ratio, self.knee, self.makeup, input_db)

    def _draw(
        self, _area: Gtk.DrawingArea, cr: cairo.Context[cairo.Surface], width: int, height: int
    ) -> None:
        size = min(width, height)
        cr.translate((width - size) / 2, (height - size) / 2)
        cr.scale(size / self.SIZE, size / self.SIZE)

        left, right = self.MARGIN, self.SIZE - self.PAD
        top, bottom = self.PAD, self.SIZE - self.MARGIN

        _fg(cr, self, 0.05)
        cr.rectangle(left, top, right - left, bottom - top)
        cr.fill()

        _fg(cr, self, 0.15)
        cr.set_line_width(0.5)
        for db in (-40, -20, 0):
            cr.move_to(self._x(db), top)
            cr.line_to(self._x(db), bottom)
            cr.move_to(left, self._y(db))
            cr.line_to(right, self._y(db))
        cr.stroke()

        _fg(cr, self, 0.6)
        cr.select_font_face("sans-serif", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        cr.set_font_size(8)
        for db in (-60, -40, -20, 0):
            label = f"{db}"
            ext = cr.text_extents(label)
            cr.move_to(left - ext.width - 3, self._y(db) + ext.height / 2)
            cr.show_text(label)
            cr.move_to(self._x(db) - ext.width / 2, bottom + ext.height + 3)
            cr.show_text(label)

        # 1:1 reference
        _fg(cr, self, 0.25)
        cr.set_line_width(1)
        cr.set_dash([3.0, 3.0])
        cr.move_to(self._x(self.DB_MIN), self._y(self.DB_MIN))
        cr.line_to(self._x(self.DB_MAX), self._y(self.DB_MAX))
        cr.stroke()
        cr.set_dash([])

        # threshold
        cr.set_source_rgba(1, 0.8, 0.2, 0.4)
        cr.move_to(self._x(self.threshold), top)
        cr.line_to(self._x(self.threshold), bottom)
        cr.stroke()

        cr.set_line_width(2)
        if not self.dsp_enabled:
            cr.set_dash([6.0, 4.0])

        # normal part (<= 0 dB) and clipped part (> 0 dB, drawn at 0 dB)
        for clipped in (False, True):
            if not self.dsp_enabled:
                _fg(cr, self, 0.5)
            elif clipped:
                cr.set_source_rgb(1, 0.3, 0.3)
            else:
                _fg(cr, self)
            drawing = False
            in_db = self.DB_MIN
            while in_db <= self.DB_MAX:
                out = self._out(in_db)
                if (out > self.DB_MAX) != clipped:
                    if drawing:
                        cr.stroke()
                    drawing = False
                else:
                    y = self._y(self.DB_MAX if clipped else max(out, self.DB_MIN))
                    if drawing:
                        cr.line_to(self._x(in_db), y)
                    else:
                        cr.move_to(self._x(in_db), y)
                        drawing = True
                in_db += 0.5
            if drawing:
                cr.stroke()

        if self.dsp_enabled and self.input_db > self.DB_MIN and self.output_db > self.DB_MIN:
            if self.input_db >= self.DB_MAX or self.output_db >= self.DB_MAX:
                cr.set_source_rgb(1.0, 0.3, 0.3)
            else:
                cr.set_source_rgb(0.2, 0.8, 1.0)
            cr.arc(
                self._x(min(self.input_db, self.DB_MAX)),
                self._y(min(self.output_db, self.DB_MAX)),
                4,
                0,
                2 * math.pi,
            )
            cr.fill()

# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drawing of routing connections (bezier curves with arrows and glow).

The colours are the accent colours of libadwaita (the GNOME palette):
lines in their standalone variant for the light or dark style (legible
on the view background), the glow in the brighter plain one.
"""

import math
from dataclasses import dataclass

import cairo
from gi.repository import Adw

from vermilion.core.constants import PC
from vermilion.core.features.levels import (
    GLOW_LAYERS,
    GLOW_MIN_DB,
    glow_intensity,
    glow_layer_params,
)

type RGB = tuple[float, float, float]

# The order keeps neighbouring cables apart also with colour vision
# deficiencies: simulated protanopia, deuteranopia and tritanopia
# (Machado et al. 2009), the smallest CIELAB distance between neighbours
# in the light and dark style is 20 (the order by hue gave 12). Slate
# (grey) is left out.
CABLE_COLOURS = (
    Adw.AccentColor.BLUE,
    Adw.AccentColor.YELLOW,
    Adw.AccentColor.TEAL,
    Adw.AccentColor.ORANGE,
    Adw.AccentColor.PURPLE,
    Adw.AccentColor.GREEN,
    Adw.AccentColor.PINK,
    Adw.AccentColor.RED,
)

# cable widths; wider with the high contrast style and for the cables of
# the port under the pointer, the others fade
LINE_WIDTH = 2.0
LINE_WIDTH_HIGH_CONTRAST = 3.0
HIGHLIGHT_EXTRA_WIDTH = 1.5
FADED_ALPHA = 0.2
# gap cleared on both sides of a cable, so that crossings can be followed
CASING = 1.5

# glow colour by level (dB): green, turning yellow, orange and red
# towards 0 dBFS
GLOW_STOPS = (
    (-18.0, Adw.AccentColor.GREEN),
    (-6.0, Adw.AccentColor.YELLOW),
    (-3.0, Adw.AccentColor.ORANGE),
    (0.0, Adw.AccentColor.RED),
)

# a connection to or from a port that is hidden
HIDDEN_COLOUR = Adw.AccentColor.RED

DASH_DOTTED = [1, 10]  # sink being reconnected by a drag
DASH = [4]  # drag line to the mouse pointer


def is_mixer(port_category: int) -> bool:
    """Mixer and DSP ports are at the top/bottom of the routing window."""
    return port_category in (PC.MIX, PC.DSP)


def _dark() -> bool:
    return Adw.StyleManager.get_default().get_dark()


def line_width() -> float:
    high_contrast = Adw.StyleManager.get_default().get_high_contrast()
    return LINE_WIDTH_HIGH_CONTRAST if high_contrast else LINE_WIDTH


def accent(colour: Adw.AccentColor, standalone: bool = True) -> RGB:
    """An accent colour; standalone: the variant for lines on the view
    background, else the brighter one (used for the translucent glow)."""
    if standalone:
        rgba = Adw.AccentColor.to_standalone_rgba(colour, _dark())
    else:
        rgba = Adw.AccentColor.to_rgba(colour)
    return rgba.red, rgba.green, rgba.blue


def line_colour(i: int) -> RGB:
    """Colour of the cable to sink i."""
    return accent(CABLE_COLOURS[i % len(CABLE_COLOURS)])


def level_colour(db: float) -> RGB:
    """Glow colour of a level (dB)."""
    lo_db, lo = GLOW_STOPS[0]
    if db <= lo_db:
        return accent(lo, False)
    for hi_db, hi in GLOW_STOPS[1:]:
        if db <= hi_db:
            t = (db - lo_db) / (hi_db - lo_db)
            a, b = accent(lo, False), accent(hi, False)
            return (
                a[0] + (b[0] - a[0]) * t,
                a[1] + (b[1] - a[1]) * t,
                a[2] + (b[2] - a[2]) * t,
            )
        lo_db, lo = hi_db, hi
    return accent(lo, False)


type Point = tuple[float, float]


@dataclass(frozen=True)
class Cable:
    """A connection from a source to a sink: a bezier curve whose shape
    depends on whether the ends are mixer/DSP ports (top/bottom of the
    view) or not (left/right)."""

    start: Point
    src_pc: int
    end: Point
    snk_pc: int

    @property
    def control_points(self) -> tuple[Point, Point]:
        (x1, y1), (x2, y2) = self.start, self.end
        x3, y3, x4, y4 = x1, y1, x2, y2
        src_mix, snk_mix = is_mixer(self.src_pc), is_mixer(self.snk_pc)

        if src_mix == snk_mix:
            f1 = 0.3
            f2 = 1 - f1
            if src_mix:  # vertical
                y3 = y1 * f2 + y2 * f1
                y4 = y1 * f1 + y2 * f2
            else:  # horizontal
                x3 = x1 * f2 + x2 * f1
                x4 = x1 * f1 + x2 * f2
        else:
            # f1 is close to 0 when approaching 45° and 0.5 near 0°/90°
            a = math.fmod(math.degrees(math.atan2(y1 - y2, x2 - x1)) + 360, 360)
            f1 = abs(math.fmod(a, 90) - 45) / 90
            f2 = 1 - f1
            if src_mix:  # bottom to right
                y3 = y1 * f2 + y2 * f1
                x4 = x1 * f1 + x2 * f2
            else:  # left to top
                x3 = x1 * f2 + x2 * f1
                y4 = y1 * f1 + y2 * f2

        return (x3, y3), (x4, y4)

    def path(self, cr: cairo.Context[cairo.Surface]) -> None:
        """Add the curve to the path of cr."""
        (x3, y3), (x4, y4) = self.control_points
        cr.move_to(*self.start)
        cr.curve_to(x3, y3, x4, y4, *self.end)

    def point_at(self, t: float = 0.5) -> tuple[float, float, float]:
        """Point and tangent angle at t (0: start, 1: end)."""
        (x1, y1), (x4, y4) = self.start, self.end
        (x2, y2), (x3, y3) = self.control_points
        ti = 1 - t
        x = ti**3 * x1 + 3 * ti**2 * t * x2 + 3 * ti * t**2 * x3 + t**3 * x4
        y = ti**3 * y1 + 3 * ti**2 * t * y2 + 3 * ti * t**2 * y3 + t**3 * y4
        dx = ti * ti * (x2 - x1) + 2 * ti * t * (x3 - x2) + t * t * (x4 - x3)
        dy = ti * ti * (y2 - y1) + 2 * ti * t * (y3 - y2) + t * t * (y4 - y3)
        return x, y, math.atan2(dy, dx)


class Painter:
    """Draws cables, their glow by the signal level and the arrows to
    hidden ports on a cairo context."""

    def __init__(self, cr: cairo.Context[cairo.Surface]) -> None:
        self.cr = cr

    def cable(
        self,
        cable: Cable,
        rgb: RGB,
        width: float = LINE_WIDTH,
        alpha: float = 1.0,
        casing: float = 0.0,
    ) -> None:
        """A cable with an arrow in the middle; casing clears a gap of that
        width on both sides first (the lines are drawn on their own
        transparent layer, so the view background shows through)."""
        cr = self.cr
        if casing > 0:
            cr.save()
            cr.set_operator(cairo.Operator.CLEAR)
            cr.set_line_width(width + 2 * casing)
            cable.path(cr)
            cr.stroke()
            cr.restore()

        cr.set_source_rgba(*rgb, alpha)
        cr.set_line_width(width)
        cable.path(cr)

        # arrow in the middle, as large as the line is wide
        scale = width / LINE_WIDTH
        mx, my, a = cable.point_at()
        cr.move_to(mx + math.cos(a) * 12 * scale, my + math.sin(a) * 12 * scale)
        for side in (-1, 1):
            cr.line_to(
                mx + math.cos(a + side * math.pi / 2) * 2 * scale,
                my + math.sin(a + side * math.pi / 2) * 2 * scale,
            )
        cr.close_path()
        cr.stroke()

    def cable_glow(self, cable: Cable, level_db: float) -> None:
        intensity = glow_intensity(level_db)
        if intensity <= 0:
            return
        cr = self.cr
        rgb = level_colour(level_db)
        cr.set_dash([])
        for layer in range(GLOW_LAYERS - 1, -1, -1):
            width, alpha = glow_layer_params(layer, intensity)
            cr.set_source_rgba(*rgb, alpha)
            cr.set_line_width(width)
            cable.path(cr)
            cr.stroke()

    def source_glow(self, point: Point, level_db: float) -> None:
        """Glow around a source that isn't connected to anything."""
        intensity = glow_intensity(level_db)
        if intensity <= 0:
            return
        cr = self.cr
        rgb = level_colour(level_db)
        cr.set_dash([])
        for layer in range(GLOW_LAYERS - 1, -1, -1):
            width, alpha = glow_layer_params(layer, intensity)
            cr.set_source_rgba(*rgb, alpha * 0.7)
            cr.arc(*point, width * 1.2, 0, 2 * math.pi)
            cr.fill()

    def hidden_arrow(self, point: Point, direction: int, level_db: float) -> None:
        """Arrow from a port showing it's connected to a hidden port.

        direction: 0 = right, 1 = left, 2 = up, 3 = down
        """
        cr = self.cr
        x, y = point
        angle = (0, math.pi, -math.pi / 2, math.pi / 2)[direction]
        bx = x + math.cos(angle) * 24
        by = y + math.sin(angle) * 24
        tx = bx + math.cos(angle) * 12
        ty = by + math.sin(angle) * 12

        intensity = glow_intensity(level_db)
        if intensity > 0:
            rgb = level_colour(level_db)
            cr.set_dash([])
            for layer in range(GLOW_LAYERS - 1, -1, -1):
                width, alpha = glow_layer_params(layer, intensity)
                cr.set_source_rgba(*rgb, alpha)
                cr.set_line_width(width)
                cr.move_to(x, y)
                cr.line_to(tx, ty)
                cr.stroke()

        cr.set_source_rgb(*accent(HIDDEN_COLOUR))
        cr.set_line_width(line_width())
        cr.move_to(x, y)
        cr.line_to(bx, by)
        cr.stroke()

        cr.move_to(tx, ty)
        cr.line_to(bx + math.cos(angle - math.pi / 2) * 4, by + math.sin(angle - math.pi / 2) * 4)
        cr.line_to(bx + math.cos(angle + math.pi / 2) * 4, by + math.sin(angle + math.pi / 2) * 4)
        cr.close_path()
        cr.fill()


__all__ = [
    "DASH",
    "DASH_DOTTED",
    "GLOW_MIN_DB",
    "Cable",
    "Painter",
    "is_mixer",
    "level_colour",
    "line_colour",
    "line_width",
]

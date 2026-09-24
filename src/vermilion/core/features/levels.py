# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Level meter polling and mapping of meters to routing sources/sinks."""

import math
from typing import TYPE_CHECKING

from gi.repository import GLib

from vermilion.core.constants import PC

if TYPE_CHECKING:
    from vermilion.core.card import Card
    from vermilion.core.ports import RoutingSnk, RoutingSrc

LEVELS_RATES = [("5 Hz", 5, 200), ("10 Hz", 10, 100), ("20 Hz", 20, 50)]
DEFAULT_LEVELS_INTERVAL_MS = 50

# glow effect configuration
GLOW_LAYERS = 4
GLOW_MAX_WIDTH = 16.0
GLOW_MIN_DB = -60.0
GLOW_MAX_DB = 0.0


def levels_hz_to_ms(hz: int) -> int:
    for _, rate_hz, ms in LEVELS_RATES:
        if rate_hz == hz:
            return ms
    return DEFAULT_LEVELS_INTERVAL_MS


def raw_to_db(value: int) -> float:
    if value <= 0:
        return -math.inf
    return 20 * math.log10(value / 4095.0)


# glow helpers (shared by the routing and mixer windows)


def glow_intensity(level_db: float) -> float:
    """0..1 from dB level, with a curve applied."""
    if level_db < GLOW_MIN_DB:
        return 0.0
    intensity = min(1.0, (level_db - GLOW_MIN_DB) / (GLOW_MAX_DB - GLOW_MIN_DB))
    return intensity * intensity


def glow_layer_params(layer: int, intensity: float) -> tuple[float, float]:
    """(width, alpha) of a glow layer."""
    frac = layer / (GLOW_LAYERS - 1)
    width = 4.0 + (GLOW_MAX_WIDTH - 4.0) * intensity * (0.3 + 0.7 * frac)
    alpha = 0.08 + intensity * 0.32 * (1.0 - 0.7 * frac)
    return width, alpha


class LevelMonitor:
    """Periodically reads the "Level Meter" control of a card.

    Stores dB values in card.routing_levels and emits
    card.levels_changed.
    """

    def __init__(self, card: Card) -> None:
        self.card = card
        self.elem = card.elem("Level Meter")
        self._timer = 0
        card.level_meter_elem = self.elem
        if self.elem:
            card.routing_levels = [-80.0] * self.elem.count
            self._init_level_indices()
            # without meters of their own, sources are measured at a sink
            # they are connected to: which one changes with the routing
            handler = card.connect("routing-changed", lambda _c: self._init_level_indices())
            card.on_destroy(lambda: card.disconnect(handler))
        card.on_destroy(self.stop)

    @property
    def available(self) -> bool:
        return self.elem is not None

    # which meter measures which port

    def _snk_level_index(self, snk: RoutingSnk) -> int:
        e = snk.elem
        if e.port_category == PC.OFF:
            return -1

        labels = self.card.level_meter_elem.meter_labels if self.card.level_meter_elem else None

        # if meter labels are available, search for a matching "Sink" label
        if labels:
            for i, label in enumerate(labels):
                if not label.startswith("Sink "):
                    continue
                # match the label as a complete word prefix
                sink_name = label[5:]
                if e.name.startswith(sink_name + " "):
                    return i
            return -1

        # without labels, meters are ordered: HW Outputs, Mixer Inputs, DSP
        # Inputs, PCM Inputs
        index = sum(self.card.routing_out_count[c] for c in range(PC.HW, e.port_category))
        index += e.port_num
        return index if index < len(self.card.routing_levels) else -1

    def _src_level_index(self, src: RoutingSrc) -> int:
        if not self.card.level_meter_elem or src.port_category == PC.OFF:
            return -1

        labels = self.card.level_meter_elem.meter_labels
        if labels:
            for i, label in enumerate(labels):
                if label.startswith("Source ") and label[7:] == src.name:
                    return i
            return -1

        # without labels, meters are at sinks only; use a connected sink
        for snk in self.card.routing_snks:
            if snk.effective_source_idx == src.id and snk.level_index >= 0:
                return snk.level_index
        return -1

    def _init_level_indices(self) -> None:
        # sinks first (sources depend on them in the no-labels case)
        for snk in self.card.routing_snks:
            snk.level_index = self._snk_level_index(snk)
        for src in self.card.routing_srcs:
            src.level_index = self._src_level_index(src)

    def start(self, interval_ms: int | None = None) -> None:
        self.stop()
        if not self.elem:
            return
        if interval_ms is None:
            interval_ms = self.card.prefs.levels_interval_ms
        self._timer = GLib.timeout_add(interval_ms, self._tick)

    def stop(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _tick(self) -> bool:
        card = self.card
        if not self.elem or not card.is_open:
            self._timer = 0
            return GLib.SOURCE_REMOVE
        values = self.elem.get_int_values()
        card.routing_levels = [raw_to_db(v) for v in values]
        card.emit("levels-changed")
        return GLib.SOURCE_CONTINUE

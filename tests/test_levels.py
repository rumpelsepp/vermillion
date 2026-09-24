# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which meter measures which port."""

from pathlib import Path

from gi.repository import GLib

from vermilion.core import sim
from vermilion.core.constants import PC
from vermilion.core.features.levels import LevelMonitor

DEMO = Path(__file__).parents[1].joinpath("demo", "Scarlett Gen 4 4i4.state")


def iterate() -> None:
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def test_source_measured_once_connected() -> None:
    card = sim.load_card(DEMO)
    card.setup()
    monitor = LevelMonitor(card)
    assert monitor.available
    iterate()

    src = card.srcs_of(PC.PCM)[0]
    for k in card.routing_snks:
        if k.effective_source_idx == src.id:
            k.elem.set_value(0)
    iterate()
    assert src.level_index < 0

    # connecting it gives it the meter of the sink
    snk = card.snks_of(PC.MIX)[0]
    assert snk.level_index >= 0
    snk.elem.set_value(src.id)
    iterate()
    assert src.level_index == snk.level_index
    monitor.stop()

# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Recording the controls of an interface and restoring them."""

from pathlib import Path

from gi.repository import GLib

from vermilion.core import sim
from vermilion.core.card import Card, Elem
from vermilion.core.device.state import DeviceState
from vermilion.core.storage import state

DEMO = Path(__file__).parents[1].joinpath("demo", "Scarlett Gen 3 18i8.state")


def iterate() -> None:
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def load() -> tuple[Card, DeviceState]:
    card = sim.load_card(DEMO)
    card.setup()
    iterate()
    return card, DeviceState(card)


def switch(card: Card) -> Elem:
    elem = card.elem("Line In 1 Level Capture Enum")
    assert elem
    return elem


def test_first_time_records() -> None:
    _card, ds = load()
    assert ds.recorded() is None
    ds.compare()
    assert ds.recorded() == ds.current()
    ds.close()


def test_changes_are_recorded() -> None:
    card, ds = load()
    ds.compare()
    elem = switch(card)
    elem.set_value(1 - elem.get_value())
    ds.flush()
    recorded = ds.recorded()
    assert recorded and recorded[elem.name] == ds.current()[elem.name]
    ds.close()


def restarted_after_restore(card: Card) -> tuple[DeviceState, Elem, int]:
    """Record, then change a control behind Vermilion's back (like
    alsa-restore) and start tracking anew."""
    ds = DeviceState(card)
    ds.compare()
    ds.close()
    elem = switch(card)
    before = elem.get_value()
    elem.set_value(1 - before)
    return DeviceState(card), elem, before


def test_differences_are_offered_and_restored() -> None:
    card, first = load()
    first.close()
    ds, elem, before = restarted_after_restore(card)
    offered = []
    ds.connect("differs", lambda _s: offered.append(True))
    ds.compare()
    assert offered and list(ds.differences) == [elem.name]
    ds.restore()
    assert elem.get_value() == before
    assert not ds.differences
    ds.close()


def test_keep_records_the_current_state() -> None:
    card, first = load()
    first.close()
    ds, elem, before = restarted_after_restore(card)
    ds.compare()
    ds.keep()
    assert elem.get_value() != before
    recorded = ds.recorded()
    assert recorded and recorded[elem.name] == ds.current()[elem.name]
    ds.close()


def test_automatic_restore() -> None:
    card, first = load()
    first.close()
    card.prefs.restore_device_state = True
    iterate()
    state.flush_now()
    ds, elem, before = restarted_after_restore(card)
    offered = []
    ds.connect("differs", lambda _s: offered.append(True))
    ds.compare()
    assert not offered and elem.get_value() == before
    ds.close()

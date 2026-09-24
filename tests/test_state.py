# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which file a value is kept in (XDG state, config and data)."""

from pathlib import Path

from gi.repository import GLib

from vermilion.core import sim
from vermilion.core.card import Card
from vermilion.core.storage import state

DEMO = Path(__file__).parents[1].joinpath("demo", "Scarlett Gen 3 18i8.state")


def iterate() -> None:
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def load() -> Card:
    card = sim.load_card(DEMO)
    card.setup()
    iterate()
    return card


def sections(path: Path) -> set[str]:
    kf = state.load_keyfile(path)
    assert kf
    return set(kf.get_groups()[0])


def test_state_and_preferences_are_separate(xdg_dirs: Path) -> None:
    card = load()
    src = card.routing_srcs[1]
    assert src.custom_name_elem
    src.custom_name_elem.set_bytes("Kick Drum")
    card.prefs.set_view("page", "mixer")
    card.prefs.levels_rate_index = 0
    iterate()
    state.flush_now()

    serial = f"{card.serial}.conf"
    state_file = xdg_dirs.joinpath("state", serial)
    config_file = xdg_dirs.joinpath("config", serial)
    assert sections(state_file) == {"device", "controls", "view"}
    assert sections(config_file) == {"device", "preferences"}
    assert "Kick Drum" in state_file.read_text()


def test_presets(xdg_dirs: Path) -> None:
    card = load()
    assert card.presets.save("Live") is None
    assert xdg_dirs.joinpath("presets", f"{card.serial}-Live.conf").exists()
    assert card.presets.names() == ["Live"]


def test_title_parts() -> None:
    card = load()
    # a simulated card's serial number is its name
    assert card.title_parts == ("Scarlett Gen 3 18i8", "")
    card.serial = "F9ZUVJE21087EC"
    assert card.title_parts == ("Scarlett Gen 3 18i8", "F9ZUVJE21087EC")
    elem = card.name_elem
    assert elem
    elem.set_bytes("Studio")
    assert card.title_parts == ("Studio", "Scarlett Gen 3 18i8")


def test_optional_elems_persist() -> None:
    card = load()
    snk = card.routing_snks[0]
    assert snk.enable_elem and snk.enable_elem.optional
    snk.enable_elem.set_value(0)
    iterate()
    state.flush_now()

    again = load()
    snk2 = again.routing_snks[0]
    assert snk2.enable_elem and snk2.enable_elem.get_value() == 0


def test_dsp_filter_type_persists() -> None:
    vocaster = Path(__file__).parents[1].joinpath("demo", "Vocaster Two.state")
    card = sim.load_card(vocaster)
    card.setup()
    name = "Line In 1 PEQ Filter 1 Type"
    elem = card.elem(name)
    assert elem and elem.optional
    elem.set_value(3)
    iterate()
    state.flush_now()

    again = sim.load_card(vocaster)
    again.setup()
    elem2 = again.elem(name)
    assert elem2 and elem2.get_value() == 3

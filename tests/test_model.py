# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Model tests on simulated cards from the demo .state files."""

from pathlib import Path

import pytest
from gi.repository import GLib

from vermilion.core import sim
from vermilion.core.card import Card
from vermilion.core.constants import PC
from vermilion.core.storage import state

DEMO_DIR = Path(__file__).parents[1].joinpath("demo")
DEMOS = sorted(DEMO_DIR.glob("*.state"))


def iterate() -> None:
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def load(path: Path) -> Card:
    card = sim.load_card(path)
    card.setup()
    iterate()
    return card


@pytest.mark.parametrize("path", DEMOS, ids=lambda p: p.name)
def test_load(path: Path) -> None:
    card = load(path)
    assert card.elems
    if card.routing_srcs:
        assert card.routing_srcs[0].name == "Off"
        for src in card.routing_srcs:
            assert src.display_name or src.port_category == PC.OFF
        for snk in card.routing_snks:
            assert snk.effective_source_idx < len(card.routing_srcs)


@pytest.mark.parametrize("path", DEMOS, ids=lambda p: p.name)
def test_toggle_all_links(path: Path) -> None:
    """Linking and unlinking every pair must keep the model consistent."""
    card = load(path)
    links = [o.link_elem for o in card.routing_srcs + card.routing_snks if o.link_elem]
    for link in links:
        old = link.get_value()
        link.set_value(0 if old else 1)
        iterate()
        link.set_value(old)
        iterate()

    # linked sinks must be routed stereo-compatibly (or off)
    for snk in card.routing_snks:
        if not snk.is_linked or not snk.is_left:
            continue
        partner = snk.partner
        assert partner is not None
        a, b = snk.elem.get_value(), partner.elem.get_value()
        if a == b:
            continue
        src_l = card.src(a)
        assert src_l is not None and src_l.partner is card.src(b)


@pytest.mark.parametrize("path", DEMOS, ids=lambda p: p.name)
def test_routing_connect(path: Path) -> None:
    card = load(path)
    if not card.routing_snks:
        return
    srcs = [s for s in card.routing_srcs[1:] if s.port_category == PC.PCM]
    snks = [s for s in card.routing_snks if s.elem.port_category == PC.HW]
    if not srcs or not snks:
        return
    src, snk = srcs[0], snks[0]
    if snk.connect_source(src):
        assert snk.effective_source_idx in (src.id, *(s.id for s in [src.partner] if s))
    snk.disconnect_source()
    assert snk.elem.get_value() == 0 or snk.routing_elem is not snk.elem

    for preset in ("clear", "direct", "preamp", "stereo_out"):
        card.apply_routing_preset(preset)


@pytest.mark.parametrize("path", DEMOS, ids=lambda p: p.name)
def test_config_roundtrip(path: Path, tmp_path: Path) -> None:
    card = load(path)
    # linked pairs keep their channels in sync; test channels separately
    for obj in card.routing_srcs + card.routing_snks:
        if obj.link_elem:
            obj.link_elem.set_value(0)
    iterate()
    conf = tmp_path.joinpath("out.conf")
    card.config.write(conf)

    # change some writable values, then load them back
    # (config files are keyed by name, so only the first of several
    # elements with the same name is saved, as in the C implementation)
    names = [e.name for e in card.elems]
    changed = []
    for elem in card.elems:
        if names.count(elem.name) > 1:
            continue
        if elem.type == 1 and elem.writable() and not elem.optional:
            changed.append((elem, elem.get_value()))
            elem.set_value(0 if elem.get_value() else 1)
    card.config.read(conf)
    iterate()
    for elem, value in changed:
        assert elem.get_value() == value, elem.name


def test_custom_names_persist(tmp_path: Path) -> None:
    path = next(p for p in DEMOS if "Gen 4 18i20" in p.name)
    card = load(path)
    src = card.routing_srcs[1]
    assert src.custom_name_elem is not None
    src.custom_name_elem.set_bytes("Kick Drum")
    iterate()
    assert src.display_name == "Kick Drum"
    state.flush_now()

    card2 = load(path)
    assert card2.routing_srcs[1].display_name == "Kick Drum"


def test_gain_db_conversions() -> None:
    path = next(p for p in DEMOS if "Gen 3 18i8" in p.name)
    card = load(path)

    elem = card.elem("Mix A Input 01 Playback Volume")
    assert elem is not None
    assert elem.max_val == 172
    # 0.5 dB per step from -80 dB
    assert elem.value_to_db(160) == pytest.approx(0.0)
    assert elem.db_to_value(0.0) == 160

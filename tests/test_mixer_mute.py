# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mute and solo of mixer inputs and mixes."""

import random
from pathlib import Path

from gi.repository import GLib

from vermilion.core import sim
from vermilion.core.card import Card, Elem
from vermilion.core.constants import PC
from vermilion.core.features.mixer_mute import MixerMute
from vermilion.core.ports import RoutingSnk, RoutingSrc
from vermilion.core.storage import state

DEMO = Path(__file__).parents[1].joinpath("demo", "Scarlett Gen 4 18i20.state")


def iterate() -> None:
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)


def load() -> tuple[Card, MixerMute]:
    card = sim.load_card(DEMO)
    card.setup()
    iterate()
    assert card.mixer_mute
    return card, card.mixer_mute


def gains(snk: RoutingSnk) -> list[Elem]:
    return [g for row in snk.card.mixer_gains if (g := row[snk.mixer_index])]


def randomize(card: Card) -> dict[str, int]:
    rnd = random.Random(1)
    for row in card.mixer_gains:
        for gain in row:
            if gain:
                gain.set_value(rnd.randint(gain.min_val + 1, gain.max_val))
    return {g.name: g.get_value() for row in card.mixer_gains for g in row if g}


def values(card: Card) -> dict[str, int]:
    return {g.name: g.get_value() for row in card.mixer_gains for g in row if g}


def unlinked(card: Card) -> list[RoutingSnk]:
    return [s for s in card.snks_of(PC.MIX) if not s.is_linked]


def test_every_input_has_switches() -> None:
    card, _ = load()
    for snk in card.snks_of(PC.MIX):
        assert snk.mute_elem and snk.solo_elem
        assert snk.mute_elem.name == f"Mixer In {snk.lr_num} Mute"


def test_mute_and_unmute() -> None:
    card, mute = load()
    before = randomize(card)
    snk = unlinked(card)[0]
    assert snk.mute_elem
    snk.mute_elem.set_value(1)
    assert mute.silenced(snk)
    for gain in gains(snk):
        assert gain.get_value() == gain.min_val
    others = {k: v for k, v in values(card).items() if k not in {g.name for g in gains(snk)}}
    assert all(before[k] == v for k, v in others.items())

    snk.mute_elem.set_value(0)
    assert values(card) == before


def dimmed(gain: Elem, original: int, db: float = 15) -> int:
    if original <= gain.min_val:
        return gain.min_val
    return max(gain.min_val, gain.db_to_value(gain.value_to_db(original) - db))


def test_solo_dims_the_others() -> None:
    card, mute = load()
    before = randomize(card)
    a, b = unlinked(card)[:2]
    assert a.solo_elem and b.solo_elem
    a.solo_elem.set_value(1)
    for snk in card.snks_of(PC.MIX):
        for g in gains(snk):
            expected = before[g.name] if snk is a else dimmed(g, before[g.name])
            assert g.get_value() == expected, (snk, g.name)

    # a second solo adds to the first
    b.solo_elem.set_value(1)
    assert not mute.silenced(a) and not mute.silenced(b)
    assert [g.get_value() for g in gains(b)] == [before[g.name] for g in gains(b)]

    a.solo_elem.set_value(0)
    b.solo_elem.set_value(0)
    assert values(card) == before


def test_solo_mutes_the_others_if_set() -> None:
    card, _ = load()
    card.prefs.solo_mutes = True
    before = randomize(card)
    a = unlinked(card)[0]
    assert a.solo_elem
    a.solo_elem.set_value(1)
    for snk in card.snks_of(PC.MIX):
        silent = all(g.get_value() == g.min_val for g in gains(snk))
        assert silent == (snk is not a), snk
    a.solo_elem.set_value(0)
    assert values(card) == before


def test_dim_amount_changed_while_soloed() -> None:
    card, mute = load()
    before = randomize(card)
    a, b = unlinked(card)[:2]
    assert a.solo_elem
    a.solo_elem.set_value(1)
    card.prefs.solo_dim_db = 6
    mute.apply()
    g = gains(b)[0]
    assert g.get_value() == dimmed(g, before[g.name], 6)
    a.solo_elem.set_value(0)
    assert values(card) == before


def test_gain_changed_while_dimmed_is_kept() -> None:
    card, _ = load()
    randomize(card)
    a, b = unlinked(card)[:2]
    assert a.solo_elem
    a.solo_elem.set_value(1)
    changed = gains(b)[0]
    changed.set_value(changed.min_val + 7)
    a.solo_elem.set_value(0)
    assert changed.get_value() == changed.min_val + 7


def test_gain_changed_while_muted_is_kept() -> None:
    card, _ = load()
    before = randomize(card)
    snk = unlinked(card)[0]
    assert snk.mute_elem
    snk.mute_elem.set_value(1)
    changed = gains(snk)[0]
    changed.set_value(changed.min_val + 5)
    snk.mute_elem.set_value(0)
    assert changed.get_value() == changed.min_val + 5
    assert all(g.get_value() == before[g.name] for g in gains(snk)[1:])


def test_linked_pair_switches_together() -> None:
    card, _ = load()
    left = next(s for s in card.snks_of(PC.MIX) if s.is_linked and s.is_left)
    right = left.partner
    assert right and left.mute_elem and right.mute_elem
    left.mute_elem.set_value(1)
    assert right.mute_elem.get_value() == 1
    left.mute_elem.set_value(0)
    assert right.mute_elem.get_value() == 0


def test_mute_survives_a_restart() -> None:
    card, _ = load()
    before = randomize(card)
    snk = unlinked(card)[0]
    assert snk.mute_elem
    snk.mute_elem.set_value(1)
    state.flush_now()
    muted = {g.name: g.get_value() for g in gains(snk)}

    # the device keeps the silenced gains; a new session must restore
    # the saved ones when unmuting
    card2 = sim.load_card(DEMO)
    for row, row2 in zip(card.mixer_gains, card2.mixer_gains, strict=True):
        for gain, gain2 in zip(row, row2, strict=True):
            if gain and gain2:
                gain2.value = gain.get_value()
    card2.setup()
    iterate()
    snk2 = next(s for s in card2.snks_of(PC.MIX) if s.lr_num == snk.lr_num)
    assert snk2.mute_elem and snk2.mute_elem.get_value() == 1
    assert {g.name: g.get_value() for g in gains(snk2)} == muted
    snk2.mute_elem.set_value(0)
    assert {g.name: g.get_value() for g in gains(snk2)} == {
        g.name: before[g.name] for g in gains(snk2)
    }


# mixes (mixer outputs)


def row_gains(src: RoutingSrc) -> list[Elem]:
    return [g for g in src.card.mixer_gains[src.mixer_index] if g]


def unlinked_mixes(card: Card) -> list[RoutingSrc]:
    return [s for s in card.srcs_of(PC.MIX) if not s.is_linked]


def test_every_mix_has_switches() -> None:
    card, _ = load()
    for src in card.srcs_of(PC.MIX):
        assert src.mute_elem and src.solo_elem
        assert src.mute_elem.name == f"Mixer Out {src.lr_num} Mute"


def test_mute_a_mix() -> None:
    card, mute = load()
    before = randomize(card)
    mix = card.srcs_of(PC.MIX)[0]
    assert mix.mute_elem
    mix.mute_elem.set_value(1)
    assert mute.silenced(mix)
    # a linked pair (Mix A–B in the demo) mutes together
    pair = [mix, mix.partner] if mix.is_linked and mix.partner else [mix]
    muted = {g.name for m in pair for g in row_gains(m)}
    assert all(g.get_value() == g.min_val for m in pair for g in row_gains(m))
    assert all(v == before[k] for k, v in values(card).items() if k not in muted)
    mix.mute_elem.set_value(0)
    assert values(card) == before


def test_solo_a_mix() -> None:
    card, _ = load()
    before = randomize(card)
    mixes = card.srcs_of(PC.MIX)
    mix = mixes[2]
    assert mix.solo_elem
    mix.solo_elem.set_value(1)
    for other in mixes:
        soloed = other.mixer_index == mix.mixer_index or other.partner is mix
        for g in row_gains(other):
            assert g.get_value() == (before[g.name] if soloed else dimmed(g, before[g.name]))
    mix.solo_elem.set_value(0)
    assert values(card) == before


def test_input_and_mix_muted_together() -> None:
    card, _ = load()
    before = randomize(card)
    snk = unlinked(card)[0]
    mix = unlinked_mixes(card)[0] if unlinked_mixes(card) else card.srcs_of(PC.MIX)[0]
    assert snk.mute_elem and mix.mute_elem
    snk.mute_elem.set_value(1)
    mix.mute_elem.set_value(1)
    # the crosspoint stays silent until both are unmuted
    cross = card.mixer_gains[mix.mixer_index][snk.mixer_index]
    assert cross
    snk.mute_elem.set_value(0)
    assert cross.get_value() == cross.min_val
    mix.mute_elem.set_value(0)
    assert values(card) == before


def test_linked_mixes_switch_together() -> None:
    card, _ = load()
    left = next(s for s in card.srcs_of(PC.MIX) if s.is_linked and s.is_left)
    right = left.partner
    assert right and left.solo_elem and right.solo_elem
    left.solo_elem.set_value(1)
    assert right.solo_elem.get_value() == 1

# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""First-run stereo links chosen from the mixer gains."""

from pathlib import Path

from vermilion.core import sim
from vermilion.core.card import Card

DEMO = Path(__file__).parents[1].joinpath("demo", "Scarlett Gen 3 18i8.state")


def link(card: Card, name: str) -> int:
    elem = card.elem(name)
    assert elem
    return elem.get_value()


def test_crosstalk_splits_the_input_not_the_mix() -> None:
    card = sim.load_card(DEMO)
    # mixer inputs 3 and 4 (a stereo source) both into both sides of
    # Mix A–B: not a stereo pair into a stereo mix
    for mix in "AB":
        for inp in ("03", "04"):
            gain = card.elem(f"Mix {mix} Input {inp} Playback Volume")
            assert gain
            gain.set_value(100)
    card.setup()

    assert not link(card, "Mixer In 3-4 Link")
    # the mix stays stereo: the inputs have a pan each
    assert link(card, "Mixer Out 1-2 Link")

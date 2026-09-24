# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mute and solo of mixer inputs and mixes (mixer outputs).

The interfaces have neither: every mixer input and output gets two
simulated switches ("Mixer In 3 Mute", "Mixer Out 1 Solo"), persisted in
the state file like the other optional controls.

An input is silent if it is muted. If any input is soloed, the others
are dimmed (by card.prefs.solo_dim_db) or, if card.prefs.solo_mutes,
silent too; the same holds for the mixes. A crosspoint of the mixer is
silent if its input or its mix is, else dimmed if one of them is.
Silencing or dimming one keeps its previous gain (in the state file
too, so that it survives a restart); it is restored when the
crosspoint is normal again, unless the gain has been changed in the
meantime (then the new gain stays).

The switches of a linked pair are kept equal (the left one wins when
linking).
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Self

from vermilion.core.asound import ELEM_TYPE_BOOLEAN
from vermilion.core.constants import PC
from vermilion.core.storage import state

if TYPE_CHECKING:
    from vermilion.core.card import Card, Elem
    from vermilion.core.ports import Port

# the states of a crosspoint besides normal
MUTED, DIMMED = "muted", "dimmed"

# suffix of the state keys holding the gains of silenced crosspoints
_SAVED_SUFFIX = " Unmuted"


class MixerMute:
    """Mute and solo switches of the mixer inputs and outputs of a card."""

    @classmethod
    def for_card(cls, card: Card) -> Self | None:
        """Mute and solo of a card with a mixer."""
        if not card.serial or not card.snks_of(PC.MIX) or not any(any(r) for r in card.mixer_gains):
            return None
        return cls(card)

    def __init__(self, card: Card) -> None:
        self.card = card
        self.inputs = card.snks_of(PC.MIX)
        self.outputs = card.srcs_of(PC.MIX)
        controls = card.state.load(state.SECTION_CONTROLS)
        # the original gains of silenced or dimmed crosspoints, by gain
        # element name
        self.saved: dict[str, int] = {}
        # (state, gain set) of the crosspoints not normal; the gain is None
        # when the user changed it
        self._applied: dict[str, tuple[str, int | None]] = {}
        for key, value in controls.items():
            if key.endswith(_SAVED_SUFFIX):
                try:
                    self.saved[key.removesuffix(_SAVED_SUFFIX)] = int(value)
                except ValueError:
                    pass

        port: Port
        for port in (*self.inputs, *self.outputs):
            mute, solo = port.control_name("Mute"), port.control_name("Solo")
            if mute and solo:
                port.mute_elem = card.optional_elem(mute, ELEM_TYPE_BOOLEAN)
                port.solo_elem = card.optional_elem(solo, ELEM_TYPE_BOOLEAN)
                for elem in (port.mute_elem, port.solo_elem):
                    elem.connect("changed", lambda e, p=port: self._switch_changed(p, e))
            if port.link_elem:
                port.link_elem.connect("changed", lambda _e, p=port: self._link_changed(p))

        self.apply()

    # state

    @staticmethod
    def muted(port: Port) -> bool:
        return bool(port.mute_elem and port.mute_elem.get_value())

    @staticmethod
    def soloed(port: Port) -> bool:
        return bool(port.solo_elem and port.solo_elem.get_value())

    def _axis(self, port: Port) -> Sequence[Port]:
        return self.outputs if port.is_src else self.inputs

    def any_solo(self, ports: Sequence[Port]) -> bool:
        return any(self.soloed(p) for p in ports)

    def silenced(self, port: Port) -> bool:
        """Is the mixer input or mix silent or dimmed because of mute or
        solo?"""
        return self._state(port) is not None

    def _state(self, port: Port) -> str | None:
        """MUTED, DIMMED or None (normal)."""
        if self.muted(port):
            return MUTED
        if self.any_solo(self._axis(port)) and not self.soloed(port):
            return MUTED if self.card.prefs.solo_mutes else DIMMED
        return None

    # changes

    def _switch_changed(self, port: Port, elem: Elem) -> None:
        # a linked pair switches together
        partner = port.partner if port.is_linked else None
        if partner:
            other = partner.mute_elem if elem is port.mute_elem else partner.solo_elem
            if other and other.get_value() != elem.get_value():
                other.set_value(elem.get_value())
        self.apply()

    def _link_changed(self, left: Port) -> None:
        right = left.partner
        if not left.is_linked or not right:
            return
        for mine, other in ((left.mute_elem, right.mute_elem), (left.solo_elem, right.solo_elem)):
            if mine and other and other.get_value() != mine.get_value():
                other.set_value(mine.get_value())

    def _save(self, name: str, value: int | None) -> None:
        if value is None:
            self.saved.pop(name, None)
        else:
            self.saved[name] = value
        key = name + _SAVED_SUFFIX
        self.card.state.save(state.SECTION_CONTROLS, key, None if value is None else str(value))

    def _target(self, gain: Elem, original: int, state: str) -> int:
        """The gain of a crosspoint in a state, from its original one."""
        if state == MUTED or original <= gain.min_val:
            return gain.min_val
        dimmed = gain.value_to_db(original) - self.card.prefs.solo_dim_db
        return max(gain.min_val, gain.db_to_value(dimmed))

    def apply(self) -> None:
        """Silence, dim or restore the gain of every crosspoint as needed."""
        mixes = {p.mixer_index: self._state(p) for p in self.outputs}
        inputs = {p.mixer_index: self._state(p) for p in self.inputs}
        for mix, row in enumerate(self.card.mixer_gains):
            for inp, gain in enumerate(row):
                if gain:
                    states = {mixes.get(mix), inputs.get(inp)}
                    state = MUTED if MUTED in states else DIMMED if DIMMED in states else None
                    self._apply(gain, state)

    def _apply(self, gain: Elem, state: str | None) -> None:
        name = gain.name
        original = self.saved.get(name)
        current = gain.get_value()
        applied = self._applied.get(name)
        if original is not None and applied is None:
            # saved before a restart: the gain is as it was left then
            applied = self._applied[name] = (
                state or MUTED,
                self._target(gain, original, state or MUTED),
            )
        # changed by the user while silenced or dimmed: keep the new gain
        if applied and applied[1] is not None and current != applied[1]:
            self._save(name, None)
            original = None
            self._applied[name] = (applied[0], None)
            applied = self._applied[name]

        if state is None:
            if original is not None:
                gain.set_value(original)
                self._save(name, None)
            self._applied.pop(name, None)
            return
        if applied and applied[0] == state:
            # dimmed by another amount (the preference changed)
            if state == DIMMED and applied[1] is not None and original is not None:
                target = self._target(gain, original, state)
                if target != applied[1]:
                    self._applied[name] = (state, target)
                    gain.set_value(target)
            return
        if original is None:
            original = current
            self._save(name, original)
        target = self._target(gain, original, state)
        self._applied[name] = (state, target)
        if current != target:
            gain.set_value(target)

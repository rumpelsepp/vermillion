# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The last known state of an interface, kept by Vermilion.

The interfaces keep their settings, but the system's ALSA state service
(alsa-restore, from alsa-utils) writes the controls saved at the last
shutdown to a sound card when it appears, overwriting them. Vermilion
records the controls of the interface while it runs
(<state dir>/<serial>-device.conf) and compares them when the interface
appears: differences are restored automatically if the user wants so,
or offered for restoring.

The comparison waits a moment after the interface appears, so that the
state service is done; nothing is recorded until then, and nothing
while differences wait for the user's decision.
"""

import logging
from typing import TYPE_CHECKING, ClassVar, Self

from gi.repository import GLib, GObject

from vermilion.core.signals import SignalSpec, signal
from vermilion.core.storage import paths, state

if TYPE_CHECKING:
    from vermilion.core.card import Card, Elem

_log = logging.getLogger(__name__)

SETTLE_MS = 3000
SAVE_DEBOUNCE_MS = 500


class DeviceState(GObject.Object):
    """Records the controls of an interface and compares them with the
    recorded ones. Emits "differs" when the user has to decide."""

    __gsignals__: ClassVar[dict[str, SignalSpec]] = {"differs": signal()}

    @classmethod
    def for_card(cls, card: Card) -> Self | None:
        """Track the state of a real interface."""
        if not card.serial or not card.device:
            return None
        device_state = cls(card)
        card.on_destroy(device_state.close)
        return device_state

    def __init__(self, card: Card) -> None:
        super().__init__()
        self.card = card
        assert card.serial
        self.path = paths.state_dir().joinpath(f"{card.serial}-device.conf")
        # the recorded controls that differ from the interface: name -> value
        self.differences: dict[str, str] = {}
        self._recording = False
        self._save_id = 0
        self._settle_id = GLib.timeout_add(SETTLE_MS, self._settled)
        self._elems = [e for e in card.elems if not e.optional and e.persistent]
        for elem in self._elems:
            elem.connect("changed", self._changed)

    def current(self) -> dict[str, str]:
        values = {}
        for elem in self._elems:
            value = elem.to_string()
            if value is not None:
                values[elem.name] = value
        return values

    def recorded(self) -> dict[str, str] | None:
        kf = state.load_keyfile(self.path)
        return state.keyfile_section(kf, state.SECTION_CONTROLS) if kf else None

    def _settled(self) -> bool:
        self._settle_id = 0
        self.compare()
        return GLib.SOURCE_REMOVE

    def compare(self) -> None:
        """Compare the interface with the recorded state."""
        recorded = self.recorded()
        if recorded is None:
            # first time: nothing to compare with
            self.keep()
            return
        current = self.current()
        self.differences = {
            name: value
            for name, value in recorded.items()
            if name in current and current[name] != value
        }
        _log.info(
            "%s: %d controls differ from the recorded state", self.card.name, len(self.differences)
        )
        if not self.differences:
            self.keep()
        elif self.card.prefs.restore_device_state:
            self.restore()
        else:
            self.emit("differs")

    def restore(self) -> None:
        """Write the recorded values to the interface."""
        for name, value in self.differences.items():
            elem = self.card.elem(name)
            if elem:
                elem.set_from_string(value)
        self.keep()

    def keep(self) -> None:
        """Accept the state of the interface and record from now on."""
        self.differences = {}
        self._recording = True
        self._save()

    def _changed(self, _elem: Elem) -> None:
        if self._recording and not self._save_id:
            self._save_id = GLib.timeout_add(SAVE_DEBOUNCE_MS, self._save)

    def _save(self) -> bool:
        self._save_id = 0
        if not paths.ensure_dir(self.path.parent):
            return GLib.SOURCE_REMOVE
        kf = GLib.KeyFile()
        for name, value in self.current().items():
            kf.set_string(state.SECTION_CONTROLS, name, value)
        try:
            kf.save_to_file(str(self.path))
        except GLib.Error as e:
            _log.warning(f"Failed to save {self.path}: {e.message}")
        return GLib.SOURCE_REMOVE

    def flush(self) -> None:
        """Write a pending change now (the application ends)."""
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save()

    def close(self) -> None:
        """Stop; the interface is gone, its controls can't be read."""
        for source in (self._settle_id, self._save_id):
            if source:
                GLib.source_remove(source)
        self._settle_id = self._save_id = 0
        self._recording = False

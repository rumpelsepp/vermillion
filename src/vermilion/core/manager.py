# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Discovery and lifecycle of cards (real and simulated)."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from gi.repository import Gio, GLib, GObject

from vermilion.core import (
    asound,
    sim,
)
from vermilion.core.asound import AlsaError
from vermilion.core.card import AlsaCard, Card
from vermilion.core.constants import Driver
from vermilion.core.device import driver
from vermilion.core.products import is_focusrite_card_name
from vermilion.core.signals import SignalSpec, signal

_log = logging.getLogger(__name__)


class CardManager(GObject.Object):
    """Finds interfaces and follows hotplug.

    Emits "card-added"(card) when a window should be created (or
    replaced) for a card and "card-removed"(card).
    """

    __gsignals__: ClassVar[dict[str, SignalSpec]] = {
        "card-added": signal(object),
        "card-removed": signal(object),
    }

    def __init__(self) -> None:
        super().__init__()
        self.cards: list[Card] = []
        self._reopen_callbacks: dict[str, Callable[[], object]] = {}
        self._monitor: Gio.FileMonitor | None = None

    # startup

    def start(self) -> None:
        self._watch_dev_snd()
        self.scan()

    def _watch_dev_snd(self) -> None:
        try:
            monitor = Gio.File.new_for_path("/dev/snd").monitor_directory(
                Gio.FileMonitorFlags.NONE, None
            )
        except GLib.Error as e:
            _log.warning(f"can't watch /dev/snd: {e.message}")
            return
        monitor.connect("changed", self._dev_snd_changed)
        self._monitor = monitor

    def _dev_snd_changed(
        self,
        _monitor: Gio.FileMonitor,
        file: Gio.File,
        _other: Gio.File | None,
        event: Gio.FileMonitorEvent,
    ) -> None:
        if event != Gio.FileMonitorEvent.CREATED:
            return
        if not (file.get_basename() or "").startswith("control"):
            return

        # can't rescan for new cards too fast
        def rescan() -> bool:
            self.scan()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add_seconds(1, rescan)

    def scan(self) -> None:
        known = {c.num for c in self.cards}
        try:
            nums = list(asound.card_numbers())
        except AlsaError as e:
            _log.warning(e)
            return

        for num in nums:
            if num in known:
                continue
            device = f"hw:{num}"
            try:
                ctl = asound.Ctl(device)
            except AlsaError:
                continue
            try:
                name = ctl.card_name()
            except AlsaError:
                ctl.close()
                continue
            if not is_focusrite_card_name(name):
                ctl.close()
                continue

            card = AlsaCard(num, device, name, ctl)
            self.cards.append(card)
            self._init_card(card)

    # real cards

    def _init_card(self, card: AlsaCard) -> None:
        card.watch(self._card_event)

        card.driver_type = driver.detect(card.device or "")
        _log.info(
            "found %s (%s, serial %s), driver %s",
            card.name,
            card.device,
            card.serial,
            card.driver_type.name,
        )

        # no controls without a user-space FCP driver: the window only says so
        if card.driver_type == Driver.FCP:
            _log.error("%s: the FCP driver is not supported yet", card.name)
            self.emit("card-added", card)
            return

        self._complete_init(card)

    def _complete_init(self, card: AlsaCard) -> None:
        card.load_elems()
        _log.debug("%s: %d elements", card.name, len(card.elems))
        card.setup()

        if card.serial:
            cb = self._reopen_callbacks.pop(card.serial, None)
            if cb:
                cb()

        self.emit("card-added", card)

    def _card_event(self, card: AlsaCard) -> bool:
        """Events of a card; False when it has gone."""
        if not card.handle_events():
            self.remove(card)
            return False
        return True

    def remove(self, card: Card) -> None:
        _log.info("removed %s", card.name)
        if card in self.cards:
            self.cards.remove(card)
        card.destroy()
        self.emit("card-removed", card)

    # simulated cards

    def add_simulated(self, path: Path) -> Card:
        """Create a simulated card from a .state file (raises StateFileError)."""
        card = sim.load_card(path)
        _log.info("simulating %s from %s", card.name, path)
        card.setup()
        self.cards.append(card)
        self.emit("card-added", card)
        return card

    # reboot handling

    def register_reopen(self, serial: str, callback: Callable[[], object]) -> None:
        self._reopen_callbacks[serial] = callback

    def unregister_reopen(self, serial: str | None) -> None:
        if serial:
            self._reopen_callbacks.pop(serial, None)

    def is_reopen_pending(self, serial: str) -> bool:
        return serial in self._reopen_callbacks

# SPDX-FileCopyrightText: 2023-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Maintenance of an interface: reboot and reset of its configuration.

(Firmware updates are left to the original alsa-scarlett-gui and the
scarlett2/fcp-tool utilities.)

There is an implementation per driver (see driver); Maintenance.of()
gives the one of a card. Resetting takes a while: it runs in a worker
thread and reports its progress through a Reporter, whose callbacks are
invoked in the GLib main loop.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar

from gi.repository import GLib

from vermilion.core.asound import strerror
from vermilion.core.constants import Driver
from vermilion.core.device.driver import ERASE_DONE, Scarlett2Hwdep

if TYPE_CHECKING:
    from vermilion.core.card import Card

_log = logging.getLogger(__name__)


class MaintenanceError(Exception):
    pass


class Reporter:
    """Progress reporting from a worker thread to the main loop.

    on_progress(text or None, percent) is called with percent -1 on
    error; on_reboot() is called when the device is about to reboot.
    """

    def __init__(
        self, on_progress: Callable[[str | None, int], object], on_reboot: Callable[[], object]
    ) -> None:
        self._on_progress = on_progress
        self._on_reboot = on_reboot

    def progress(self, text: str | None, percent: int) -> None:
        def call() -> bool:
            self._on_progress(text, percent)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(call)

    def error(self, text: str) -> None:
        self.progress(text, -1)

    def reboot(self) -> None:
        def call() -> bool:
            self._on_reboot()
            return GLib.SOURCE_REMOVE

        GLib.idle_add(call)


class Maintenance:
    """The maintenance operations of a card, by its driver."""

    driver: ClassVar[Driver]

    def __init__(self, card: Card) -> None:
        self.card = card

    @staticmethod
    def of(card: Card) -> Maintenance | None:
        """The implementation for the driver of a card (None if it has no
        maintenance operations)."""
        for cls in (Scarlett2Maintenance,):
            if card.driver_type == cls.driver:
                return cls(card)
        return None

    def reboot(self) -> None:
        """Reboot the device; raises MaintenanceError."""
        raise NotImplementedError

    def reset_config(self, reporter: Reporter) -> None:
        """Erase the configuration of the device and reboot it (runs in the
        calling thread, see start_reset_config())."""
        _log.info("resetting the configuration of %s (%s)", self.card.name, type(self).__name__)
        reporter.progress("Resetting configuration...", 0)
        # the state kept by the application goes too
        self.card.state.remove()
        self._erase_config(reporter)

    def start_reset_config(self, reporter: Reporter) -> threading.Thread:
        """reset_config() in a worker thread."""
        thread = threading.Thread(target=self.reset_config, args=(reporter,), daemon=True)
        thread.start()
        return thread

    def _erase_config(self, reporter: Reporter) -> None:
        raise NotImplementedError


class Scarlett2Maintenance(Maintenance):
    """Via the hwdep interface of the Scarlett2 driver."""

    driver = Driver.HWDEP

    def _open(self) -> Scarlett2Hwdep:
        hwdep, err = Scarlett2Hwdep.open(self.card.device or "")
        if not hwdep:
            raise MaintenanceError(f"Unable to open hwdep interface: {strerror(err)}")
        return hwdep

    def reboot(self) -> None:
        _log.info("rebooting %s via hwdep", self.card.name)
        with self._open() as hwdep:
            err = hwdep.reboot()
        if err < 0:
            raise MaintenanceError(f"Unable to reboot device: {strerror(err)}")

    def _erase_config(self, reporter: Reporter) -> None:
        try:
            hwdep = self._open()
        except MaintenanceError as e:
            reporter.error(str(e))
            return
        with hwdep:
            err = hwdep.erase_settings()
            if err < 0:
                reporter.error(f"Unable to reset configuration: {strerror(err)}")
                return
            while (p := hwdep.erase_progress()) != ERASE_DONE:
                if p < 0:
                    reporter.error(f"Unable to get erase progress: {strerror(p)}")
                    return
                reporter.progress(None, p)
                time.sleep(0.05)
            reporter.reboot()
            hwdep.reboot()

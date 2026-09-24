# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The configuration of a card in files.

The native format (.conf) is a key file with [device] and [controls]
sections; ALSA state files (.state) are saved and restored by running
alsactl.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import GLib

from vermilion.core.storage.state import SECTION_CONTROLS, SECTION_DEVICE, keyfile_section

if TYPE_CHECKING:
    from vermilion.core.card import Card

_log = logging.getLogger(__name__)


class Configuration:
    """Writes and reads the configuration of a card."""

    def __init__(self, card: Card) -> None:
        self.card = card

    def write(self, path: Path) -> None:
        """Write a .conf key file; raises GLib.Error on failure."""
        card = self.card
        kf = GLib.KeyFile()
        if card.serial:
            kf.set_string(SECTION_DEVICE, "serial", card.serial)
        if card.name:
            kf.set_string(SECTION_DEVICE, "model", card.name)
        for elem in card.elems:
            value = elem.to_string() if elem.persistent else None
            if value is not None:
                kf.set_string(SECTION_CONTROLS, elem.name, value)
        kf.save_to_file(str(path))
        _log.info("saved the configuration of %s to %s", card.name, path)

    def read(self, path: Path) -> None:
        """Read a .conf key file; raises GLib.Error on failure."""
        kf = GLib.KeyFile()
        kf.load_from_file(str(path), GLib.KeyFileFlags.NONE)
        controls = keyfile_section(kf, SECTION_CONTROLS)
        _log.info("loading the configuration of %s from %s", self.card.name, path)

        # two passes: some elements may be read-only until other controls
        # (like enable switches) are set first
        for _ in range(2):
            for key, value in controls.items():
                elem = self.card.elem(key)
                if elem and elem.writable():
                    elem.set_from_string(value)

    def save(self, path: Path) -> str | None:
        """Write a .conf file (the suffix is added if missing); returns an
        error message or None."""
        if path.suffix != ".conf":
            path = path.with_name(f"{path.name}.conf")
        try:
            self.write(path)
        except GLib.Error:
            return f"Error saving to {path}"
        return None

    def load(self, path: Path) -> str | None:
        """Read a .conf file; returns an error message or None."""
        try:
            self.read(path)
        except GLib.Error:
            return f"Error loading from {path}"
        return None

    def alsactl(self, cmd: str, path: Path) -> str | None:
        """Run "alsactl store/restore" on an ALSA state file; returns an
        error message or None."""
        card = self.card
        if not card.device:
            return f"alsactl {cmd}: {card.name} is not a real interface"
        alsactl = shutil.which("alsactl") or "/usr/sbin/alsactl"
        argv = [alsactl, cmd, card.device, "-I", "-f", str(path)]
        _log.info("running %s", " ".join(argv))
        try:
            result = subprocess.run(argv, capture_output=True, text=True, check=False)
        except OSError as e:
            error = str(e)
        else:
            if result.returncode == 0:
                return None
            error = f"{result.stdout}\n{result.stderr}"
        return f"Error running “alsactl {cmd} {card.device} -f {path}”: {error}"

# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-device state and preferences files (see paths).

Each device (by serial number) has a state file and a preferences file;
the section decides which one a value goes to: SECTION_PREFERENCES is
kept in the preferences file, all others in the state file.

Values are written with a short debounce so that bursts of changes
(e.g. dragging a slider) result in a single file write.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import GLib

from vermilion.core.storage import paths

if TYPE_CHECKING:
    from vermilion.core.card import Card

_log = logging.getLogger(__name__)

SECTION_DEVICE = "device"
SECTION_CONTROLS = "controls"
SECTION_VIEW = "view"
SECTION_PREFERENCES = "preferences"

SAVE_DEBOUNCE_MS = 100

_pending: dict[Path, list[tuple[str, str, str]]] = {}  # path -> entries
_device_written: set[Path] = set()  # paths
_timeout_id = 0


def state_path(serial: str) -> Path:
    return paths.state_dir().joinpath(f"{serial}.conf")


def preferences_path(serial: str) -> Path:
    return paths.config_dir().joinpath(f"{serial}.conf")


def _path(serial: str, section: str) -> Path:
    return preferences_path(serial) if section == SECTION_PREFERENCES else state_path(serial)


def load_keyfile(path: Path) -> GLib.KeyFile | None:
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(str(path), GLib.KeyFileFlags.NONE)
    except GLib.Error:
        return None
    return kf


def keyfile_section(kf: GLib.KeyFile, section: str) -> dict[str, str]:
    """Return a dict of all key/value pairs in a section."""
    try:
        keys, _ = kf.get_keys(section)
    except GLib.Error:
        return {}
    values = {}
    for key in keys:
        try:
            values[key] = kf.get_string(section, key)
        except GLib.Error:
            pass
    return values


def _flush() -> bool:
    global _timeout_id
    _timeout_id = 0

    for path, entries in _pending.items():
        if not paths.ensure_dir(path.parent):
            continue
        kf = load_keyfile(path) or GLib.KeyFile()
        for section, key, value in entries:
            kf.set_string(section, key, value)
        _log.debug("writing %s", path)
        try:
            kf.save_to_file(str(path))
        except GLib.Error as e:
            _log.warning(f"Failed to save state file {path}: {e.message}")

    _pending.clear()
    return GLib.SOURCE_REMOVE


def flush_now() -> None:
    """Write pending changes immediately (e.g. on application exit)."""
    if _timeout_id:
        GLib.source_remove(_timeout_id)
    _flush()


def _queue(path: Path, entries: list[tuple[str, str, str]]) -> None:
    """Write entries (section, key, value) to a file, debounced."""
    global _timeout_id
    _pending.setdefault(path, []).extend(entries)
    if _timeout_id:
        GLib.source_remove(_timeout_id)
    _timeout_id = GLib.timeout_add(SAVE_DEBOUNCE_MS, _flush)


class CardState:
    """The state and preferences files of a card, by its serial number
    (nothing is kept for a card without one)."""

    def __init__(self, card: Card) -> None:
        self.card = card

    def load(self, section: str) -> dict[str, str]:
        """A section of the file (empty if unavailable)."""
        serial = self.card.serial
        kf = load_keyfile(_path(serial, section)) if serial else None
        return keyfile_section(kf, section) if kf else {}

    def save(self, section: str, key: str, value: str | None) -> bool:
        """Save a value (debounced); None saves an empty one."""
        card = self.card
        if not card.serial or not section or not key:
            return False
        path = _path(card.serial, section)
        entries = [(section, key, value if value is not None else "")]
        # also ensure the [device] section has serial and model
        if path not in _device_written:
            _device_written.add(path)
            entries.append((SECTION_DEVICE, "serial", card.serial))
            if card.name:
                entries.append((SECTION_DEVICE, "model", card.name))
        _queue(path, entries)
        return True

    def remove(self) -> bool:
        """Remove the state file."""
        if not self.card.serial:
            return False
        try:
            state_path(self.card.serial).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            _log.warning(f"Failed to remove state file: {e}")
            return False
        return True

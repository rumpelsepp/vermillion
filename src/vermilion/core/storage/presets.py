# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Named configuration presets (<presets dir>/<serial>-<name>.conf, see paths)."""

from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import GLib

from vermilion.core.storage import paths

if TYPE_CHECKING:
    from vermilion.core.card import Card


def valid_name(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name


class Presets:
    """The presets of a card, by its serial number."""

    def __init__(self, card: Card) -> None:
        self.card = card

    def _path(self, name: str) -> Path:
        return paths.presets_dir().joinpath(f"{self.card.serial}-{name}.conf")

    def names(self) -> list[str]:
        """The sorted names of the presets."""
        prefix = f"{self.card.serial}-"
        try:
            files = list(paths.presets_dir().iterdir())
        except OSError:
            return []
        return sorted(
            f.stem.removeprefix(prefix)
            for f in files
            if f.name.startswith(prefix) and f.suffix == ".conf"
        )

    def load(self, name: str) -> str | None:
        """Load a preset; returns an error message or None."""
        try:
            self.card.config.read(self._path(name))
        except GLib.Error:
            return f'Error loading preset "{name}"'
        return None

    def save(self, name: str) -> str | None:
        """Save a preset; returns an error message or None."""
        if not paths.ensure_dir(paths.presets_dir()):
            return f'Error saving preset "{name}"'
        try:
            self.card.config.write(self._path(name))
        except GLib.Error:
            return f'Error saving preset "{name}"'
        return None

    def delete(self, name: str) -> bool:
        try:
            self._path(name).unlink()
            return True
        except OSError:
            return False

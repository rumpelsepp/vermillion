# SPDX-FileCopyrightText: 2026 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-card preferences and window state (see state)."""

from typing import TYPE_CHECKING

from vermilion.core.features.levels import DEFAULT_LEVELS_INTERVAL_MS, LEVELS_RATES, levels_hz_to_ms
from vermilion.core.storage.state import SECTION_PREFERENCES, SECTION_VIEW

if TYPE_CHECKING:
    from vermilion.core.card import Card

KEY_BOTTOM_RIGHT_LABELS = "mixer-show-bottom-right-labels"
KEY_LEVELS_RATE = "levels-update-rate"
KEY_RESTORE_DEVICE_STATE = "restore-device-state"
KEY_SOLO_DIM_DB = "solo-dim-db"
KEY_SOLO_MUTES = "solo-mutes"

DEFAULT_SOLO_DIM_DB = 15


class Prefs:
    """The preferences of a card (saved in its preferences file) and the
    state of its window (in its state file)."""

    def __init__(self, card: Card) -> None:
        self.card = card
        self._bottom_right_labels = False
        self._restore_device_state = False
        self._solo_dim_db = DEFAULT_SOLO_DIM_DB
        self._solo_mutes = False
        self.levels_interval_ms = DEFAULT_LEVELS_INTERVAL_MS

    def load(self) -> None:
        values = self.card.state.load(SECTION_PREFERENCES)
        self._bottom_right_labels = values.get(KEY_BOTTOM_RIGHT_LABELS) == "true"
        self._restore_device_state = values.get(KEY_RESTORE_DEVICE_STATE) == "true"
        self._solo_mutes = values.get(KEY_SOLO_MUTES) == "true"
        try:
            self._solo_dim_db = int(values.get(KEY_SOLO_DIM_DB, DEFAULT_SOLO_DIM_DB))
        except ValueError:
            self._solo_dim_db = DEFAULT_SOLO_DIM_DB
        try:
            hz = int(values.get(KEY_LEVELS_RATE, "0"))
        except ValueError:
            hz = 0
        self.levels_interval_ms = levels_hz_to_ms(hz)

    def _save(self, key: str, value: str) -> None:
        self.card.state.save(SECTION_PREFERENCES, key, value)

    @property
    def show_bottom_right_labels(self) -> bool:
        """Mixer labels below and right of the mixer too."""
        return self._bottom_right_labels

    @show_bottom_right_labels.setter
    def show_bottom_right_labels(self, show: bool) -> None:
        self._bottom_right_labels = bool(show)
        self._save(KEY_BOTTOM_RIGHT_LABELS, "true" if show else "false")

    @property
    def restore_device_state(self) -> bool:
        """Restore changes to the interface made while the application
        wasn't running without asking (see device.state)."""
        return self._restore_device_state

    @restore_device_state.setter
    def restore_device_state(self, on: bool) -> None:
        self._restore_device_state = bool(on)
        self._save(KEY_RESTORE_DEVICE_STATE, "true" if on else "false")

    @property
    def solo_dim_db(self) -> int:
        """By how many dB solo dims the other mixer inputs or mixes."""
        return self._solo_dim_db

    @solo_dim_db.setter
    def solo_dim_db(self, db: int) -> None:
        self._solo_dim_db = int(db)
        self._save(KEY_SOLO_DIM_DB, str(self._solo_dim_db))

    @property
    def solo_mutes(self) -> bool:
        """Solo mutes the other mixer inputs or mixes (instead of dimming)."""
        return self._solo_mutes

    @solo_mutes.setter
    def solo_mutes(self, on: bool) -> None:
        self._solo_mutes = bool(on)
        self._save(KEY_SOLO_MUTES, "true" if on else "false")

    @property
    def levels_rate_index(self) -> int:
        """The level meter update rate, as an index of LEVELS_RATES."""
        for ms in (self.levels_interval_ms, DEFAULT_LEVELS_INTERVAL_MS):
            for i, (_, _, rate_ms) in enumerate(LEVELS_RATES):
                if rate_ms == ms:
                    return i
        return 0

    @levels_rate_index.setter
    def levels_rate_index(self, index: int) -> None:
        _, hz, ms = LEVELS_RATES[index]
        self.levels_interval_ms = ms
        self._save(KEY_LEVELS_RATE, str(hz))

    # window state (visible page, detached pages, tabs, shown channels)

    def view(self, key: str) -> str | None:
        return self.card.state.load(SECTION_VIEW).get(key)

    def set_view(self, key: str, value: str) -> None:
        self.card.state.save(SECTION_VIEW, key, value)

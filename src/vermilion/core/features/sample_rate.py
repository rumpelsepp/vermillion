# SPDX-FileCopyrightText: 2024-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sample rate and PCM channel availability from /proc/asound/cardN/stream0."""

import re
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import GLib

from vermilion.core.constants import get_sample_rate_category

if TYPE_CHECKING:
    from vermilion.core.card import Card

_ALTSET_RE = re.compile(r"Altset (\d+)")
_CHANNELS_RE = re.compile(r"Channels: (\d+)")
_ALTSET_STATUS_RE = re.compile(r"Altset = (\d+)")
_FREQ_RE = re.compile(r"Momentary freq = (\d+) Hz")


def _parse_max_rate(line: str) -> int:
    pos = line.find("Rates: ")
    if pos < 0:
        return 0
    rates = [int(x) for x in re.findall(r"\d+", line[pos + 7 :])]
    return max(rates, default=0)


def format_sample_rate(value: int) -> str:
    if not value:
        return "N/A"
    if value % 1000 == 0:
        return f"{value // 1000}kHz"
    return f"{value / 1000:.1f}kHz"


class SampleRateMonitor:
    """Polls the stream status once a second.

    Updates card.current_sample_rate, card.pcm_{playback,capture}_channels
    and the HW I/O limits; emits card.sample_rate_changed(rate,
    is_current) and card.availability_changed.
    """

    def __init__(self, card: Card) -> None:
        self.card = card
        self.path: Path | None = None
        self.sample_rate = -1
        self.is_current = False
        self.last_valid_sample_rate = 0
        self.last_valid_playback_altset = 0
        self.last_valid_capture_altset = 0
        self.capture_altset_max_rate = [0] * 4
        self._timer = 0

        if not card.is_simulated:
            self.path = Path("/proc/asound").joinpath(f"card{card.num}", "stream0")
            self._parse_altset_channels()
            self._timer = GLib.timeout_add_seconds(1, self._update)
        card.on_destroy(self.stop)

        self._update()

    def stop(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    @property
    def supported_rates(self) -> list[int]:
        """The sample rates of the USB audio streams."""
        rates = {
            int(r)
            for line in self._read_lines() or []
            if "Rates: " in line
            for r in re.findall(r"\d+", line[line.find("Rates: ") + 7 :])
        }
        return sorted(rates)

    def _read_lines(self) -> list[str] | None:
        if not self.path:
            return None
        try:
            return self.path.read_text().splitlines(keepends=True)
        except OSError:
            return None

    def _parse_altset_channels(self) -> None:
        card = self.card
        lines = self._read_lines()
        if not lines:
            return

        section = 0  # 1 = Playback, 2 = Capture
        altset = 0
        for line in lines:
            if line.startswith("Playback:"):
                section, altset = 1, 0
                continue
            if line.startswith("Capture:"):
                section, altset = 2, 0
                continue
            if not section:
                continue

            m = _ALTSET_RE.search(line)
            if m:
                if "Altset =" in line:
                    continue
                altset = int(m.group(1))
                if 0 < altset <= 3:
                    card.altset_count = max(card.altset_count, altset)
                continue

            if not 0 < altset <= 3:
                continue

            m = _CHANNELS_RE.search(line)
            if m:
                if section == 1:
                    card.playback_altset_channels[altset] = int(m.group(1))
                else:
                    card.capture_altset_channels[altset] = int(m.group(1))

            if section == 2:
                rate = _parse_max_rate(line)
                if rate > 0:
                    self.capture_altset_max_rate[altset] = rate

    def _capture_altset_for_rate(self, rate: int) -> int:
        if rate <= 0:
            return 0
        rate_cat = get_sample_rate_category(rate)
        best, best_cat = 0, -1
        for i in range(1, 4):
            max_rate = self.capture_altset_max_rate[i]
            if max_rate <= 0:
                continue
            cat = get_sample_rate_category(max_rate)
            if cat >= rate_cat and (best == 0 or cat < best_cat):
                best, best_cat = i, cat
        return best

    def _read_status(self) -> tuple[int, int, int]:
        """Return (sample_rate, playback_altset, capture_altset)."""
        lines = self._read_lines() if self.path else None
        if not lines:
            return 0, 0, 0

        rate = playback_altset = capture_altset = 0
        section = 0
        in_status = False
        for line in lines:
            if line.startswith("Playback:"):
                section, in_status = 1, True
                continue
            if line.startswith("Capture:"):
                section, in_status = 2, True
                continue

            if in_status and "Interface " in line and "Interface =" not in line:
                in_status = False

            if in_status:
                m = _ALTSET_STATUS_RE.search(line)
                if m:
                    if section == 1:
                        playback_altset = int(m.group(1))
                    elif section == 2:
                        capture_altset = int(m.group(1))

            if section == 1:
                m = _FREQ_RE.search(line)
                if m:
                    rate = int(m.group(1))

        return rate, playback_altset, capture_altset

    def _update(self) -> bool:
        card = self.card
        rate, playback_altset, capture_altset = self._read_status()

        if rate > 0:
            self.last_valid_sample_rate = rate
            if playback_altset > 0:
                self.last_valid_playback_altset = playback_altset
            if capture_altset > 0:
                self.last_valid_capture_altset = capture_altset

        if rate > 0:
            display_rate, is_current = rate, True
        else:
            display_rate, is_current = self.last_valid_sample_rate, False

        if display_rate != self.sample_rate or is_current != self.is_current:
            self.sample_rate = display_rate
            self.is_current = is_current
            card.emit("sample-rate-changed", display_rate, is_current)

        use_playback = playback_altset or self.last_valid_playback_altset
        if capture_altset > 0:
            use_capture = capture_altset
        elif self.last_valid_capture_altset > 0:
            use_capture = self.last_valid_capture_altset
        else:
            use_capture = self._capture_altset_for_rate(
                rate if rate > 0 else self.last_valid_sample_rate
            )

        old_playback = card.pcm_playback_channels
        old_capture = card.pcm_capture_channels

        if 0 < use_playback <= 3:
            card.pcm_playback_channels = card.playback_altset_channels[use_playback]
        if 0 < use_capture <= 3:
            card.pcm_capture_channels = card.capture_altset_channels[use_capture]

        changed = (
            old_playback != card.pcm_playback_channels or old_capture != card.pcm_capture_channels
        )

        use_rate = rate if rate > 0 else self.last_valid_sample_rate
        old_cat = get_sample_rate_category(card.current_sample_rate)
        new_cat = get_sample_rate_category(use_rate)
        card.current_sample_rate = use_rate

        if old_cat != new_cat:
            card.update_io_limits()
            changed = True

        if changed:
            card.emit("availability-changed")

        return GLib.SOURCE_CONTINUE

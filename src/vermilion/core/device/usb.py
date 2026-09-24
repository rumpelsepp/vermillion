# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Focusrite devices on the USB bus, from sysfs."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self

from vermilion.core.products import FOCUSRITE_VID, by_pid

if TYPE_CHECKING:
    from vermilion.core.card import Card

USB_DEVICES = Path("/sys/bus/usb/devices")

_SPEEDS = {1: "Low Speed", 12: "Full Speed", 480: "High Speed", 5000: "SuperSpeed"}


def read_sysfs(path: Path) -> str | None:
    """The stripped contents of a (sysfs or procfs) file, or None."""
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _bcd(value: str | None) -> str:
    """ "0645" -> "6.45"."""
    if not value or len(value) != 4:
        return value or ""
    return f"{int(value[:2])}.{value[2:]}"


@dataclass(frozen=True)
class UsbDevice:
    """A Focusrite device on the USB bus."""

    path: Path
    pid: int
    product: str
    manufacturer: str
    serial: str
    release: str
    speed_mbps: int
    usb_version: str
    alsa_cards: tuple[int, ...]

    @classmethod
    def at(cls, path: Path) -> Self | None:
        """The device of a sysfs directory (None if it isn't a Focusrite
        device)."""
        try:
            vid = int(read_sysfs(path.joinpath("idVendor")) or "", 16)
            pid = int(read_sysfs(path.joinpath("idProduct")) or "", 16)
        except ValueError:
            return None
        if vid != FOCUSRITE_VID:
            return None
        cards = path.glob("*:*/sound/card[0-9]*")
        speed = read_sysfs(path.joinpath("speed")) or "0"
        return cls(
            path=path,
            pid=pid,
            product=read_sysfs(path.joinpath("product")) or "",
            manufacturer=read_sysfs(path.joinpath("manufacturer")) or "",
            serial=read_sysfs(path.joinpath("serial")) or "",
            release=_bcd(read_sysfs(path.joinpath("bcdDevice"))),
            speed_mbps=int(float(speed)) if speed.replace(".", "").isdigit() else 0,
            usb_version=read_sysfs(path.joinpath("version")) or "",
            alsa_cards=tuple(sorted(int(c.name[4:]) for c in cards)),
        )

    @classmethod
    def all(cls) -> list[Self]:
        """The Focusrite devices on the USB bus."""
        devices = []
        for path in sorted(USB_DEVICES.glob("[0-9]*")):
            if ":" in path.name:  # interfaces, not devices
                continue
            device = cls.at(path)
            if device:
                devices.append(device)
        return devices

    @classmethod
    def of_card(cls, card: Card) -> Self | None:
        """The device of a (real) card."""
        if card.is_simulated:
            return None
        # controlC<N>/device is the sound card, whose device is the USB
        # interface; its parent is the USB device
        interface = Path("/sys/class/sound").joinpath(f"controlC{card.num}", "device", "device")
        return cls.at(interface.resolve().parent)

    @property
    def location(self) -> str:
        """Bus and port path, e.g. "3-6.4.2"."""
        return self.path.name

    @property
    def model(self) -> str:
        product = by_pid(self.pid)
        if product:
            return product.name
        return self.product or f"{FOCUSRITE_VID:04x}:{self.pid:04x}"

    @property
    def speed(self) -> str | None:
        if not self.speed_mbps:
            return None
        name = _SPEEDS.get(self.speed_mbps)
        return f"{name} ({self.speed_mbps} Mbit/s)" if name else f"{self.speed_mbps} Mbit/s"

    def status(self, card: Card | None) -> str:
        """What the device is to the application (e.g. the card itself)."""
        if card and not card.is_simulated and card.num in self.alsa_cards:
            return "this interface"
        if not by_pid(self.pid):
            return "not supported"
        if not self.alsa_cards:
            return "no ALSA sound card (driver not loaded, or in MSD mode?)"
        return ", ".join(f"ALSA card {n}" for n in self.alsa_cards)

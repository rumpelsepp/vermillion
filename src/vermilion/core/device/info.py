# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Everything known about an interface and the system, for the "Device
Information" dialog and bug reports.

The information comes from the model (card, elements, routing ports),
from /proc/asound and from the USB device in sysfs. It is a snapshot:
sections of labelled values, also available as plain text.
"""

import platform
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vermilion import __version__
from vermilion.core import asound
from vermilion.core.constants import HW, HW_TYPE_NAMES, PC
from vermilion.core.device.usb import UsbDevice
from vermilion.core.features.sample_rate import format_sample_rate
from vermilion.core.products import FOCUSRITE_VID

if TYPE_CHECKING:
    from vermilion.core.card import Card, Elem


@dataclass(frozen=True)
class Row:
    label: str
    value: str


@dataclass
class Section:
    title: str
    rows: list[Row] = field(default_factory=list)

    def add(self, label: str, value: object) -> None:
        """Add a row; None and "" are left out."""
        if value is not None and value != "":
            self.rows.append(Row(label, str(value)))


def _count(n: int, what: str) -> str:
    return f"{n} {what}{'' if n == 1 else 's'}"


def _in_out(inputs: int, outputs: int) -> str | None:
    if not inputs and not outputs:
        return None
    return f"{_count(inputs, 'input')}, {_count(outputs, 'output')}"


def _text(elem: Elem | None) -> str | None:
    return elem.value_text if elem else None


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


class DeviceInfo:
    """Everything known about an interface (or, without one, the Focusrite
    devices on the USB bus) and the system, as sections of labelled
    values; extra rows (e.g. versions of the GUI libraries) go to the
    system section."""

    def __init__(self, card: Card | None, extra: list[Row] | None = None) -> None:
        self.card = card
        self.sections: list[Section] = []
        if card:
            self.sections += self._card_sections(card)
        self.sections.append(self._usb_section())
        self.sections.append(self._system_section(extra or []))

    def as_text(self) -> str:
        """Plain text, e.g. for a bug report."""
        parts = []
        for section in self.sections:
            lines = [f"{section.title}:"]
            lines += [f"  {row.label}: {row.value}" for row in section.rows]
            parts.append("\n".join(lines))
        return "\n\n".join(parts) + "\n"

    # the interface

    def _card_sections(self, card: Card) -> list[Section]:
        interface = Section("Interface")
        interface.add("Model", card.product.name if card.product else card.name)
        interface.add("Name", card.custom_name)
        if card.is_simulated:
            interface.add("Simulated", "yes, from a state file")
        else:
            interface.add("Serial number", card.serial)
            interface.add("ALSA card", f"{card.device} ({card.name})")
            interface.add("USB ID", f"{FOCUSRITE_VID:04x}:{card.pid:04x}")

        driver = Section("Driver and Firmware")
        driver.add("Driver", card.driver_description)
        if card.firmware_version is not None:
            driver.add("Firmware version", card.firmware_version)
            required = card.required_firmware_version
            if required:
                status = "too old" if card.firmware_too_old else "OK"
                driver.add("Firmware required by the driver", f"{required} ({status})")
        driver.add("ALSA controls", len(card.elems))

        audio = Section("Audio")
        monitor = card.sample_rate
        if monitor and monitor.sample_rate > 0:
            rate = format_sample_rate(monitor.sample_rate)
            audio.add("Sample rate", rate if monitor.is_current else f"{rate} (last used)")
        elif not card.is_simulated:
            audio.add("Sample rate", "not streaming")
        if monitor and not card.is_simulated:
            rates = ", ".join(format_sample_rate(r) for r in monitor.supported_rates)
            audio.add("Supported sample rates", rates)
        audio.add(
            "Clock source", _text(card.first_elem("Clock Source Clock Source", "Sync Clock Source"))
        )
        audio.add("Sync status", _text(card.first_elem("Sync Status", "Sample Clock Sync Status")))
        if card.digital_io_mode_elem:
            audio.add("Digital I/O mode", _text(card.digital_io_mode_elem))

        io = Section("Inputs and Outputs")
        for hw_type in HW:
            inputs = [s for s in card.routing_srcs if s.port_category == PC.HW]
            outputs = [s for s in card.routing_snks if s.port_category == PC.HW]
            io.add(
                HW_TYPE_NAMES[hw_type],
                _in_out(
                    sum(1 for s in inputs if s.hw_type == hw_type),
                    sum(1 for s in outputs if s.hw_type == hw_type),
                ),
            )
        capture, playback = card.routing_out_count[PC.PCM], card.routing_in_count[PC.PCM]
        if capture or playback:
            io.add("Computer (PCM)", f"{capture} capture, {playback} playback channels")
        io.add("Mixer", _in_out(card.routing_out_count[PC.MIX], card.routing_in_count[PC.MIX]))
        io.add("DSP", _in_out(card.routing_out_count[PC.DSP], card.routing_in_count[PC.DSP]))
        linked = sum(1 for p in card.ports if p.is_left and p.is_linked)
        if linked:
            io.add("Stereo pairs", linked)

        features = Section("Features")
        features.add("Level meters", _yes_no(card.has_levels))
        features.add("Talkback", _yes_no(card.has_talkback))
        features.add("Speaker switching", _yes_no(card.has_speaker_switching))
        features.add("DSP", _yes_no(card.dsp is not None))
        features.add("MSD mode", _text(card.first_elem("MSD Mode Switch")))

        sections = [interface, driver, audio, io, features]

        usb = UsbDevice.of_card(card)
        if usb:
            usb_info = Section("USB")
            usb_info.add("Manufacturer", usb.manufacturer)
            usb_info.add("Product", usb.product)
            usb_info.add("Device release", usb.release)
            usb_info.add("Speed", usb.speed)
            usb_info.add("USB version", usb.usb_version)
            usb_info.add("Port", usb.location)
            sections.append(usb_info)

        return sections

    # the USB bus and the system

    def _usb_section(self) -> Section:
        """All Focusrite USB devices, e.g. to see a second interface or one
        without a sound card."""
        section = Section("Focusrite USB Devices")
        for device in UsbDevice.all():
            details = [device.serial, device.location, device.status(self.card)]
            section.add(device.model, " · ".join(d for d in details if d))
        if not section.rows:
            section.add("None found", "no Focusrite device is connected via USB")
        return section

    @staticmethod
    def _system_section(extra: list[Row]) -> Section:
        """Versions of the application, the kernel and the libraries."""
        section = Section("System")
        section.add("Vermilion", __version__)
        section.add("Linux kernel", platform.release())
        section.add("alsa-lib", asound.library_version())
        section.add("Python", platform.python_version())
        section.rows += extra
        return section

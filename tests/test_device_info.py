# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Device information: sections of the demo cards and USB device detection."""

from pathlib import Path

import pytest
from gi.repository import GLib

from vermilion.core import sim
from vermilion.core.card import Card
from vermilion.core.device import usb
from vermilion.core.device.info import DeviceInfo, Row, Section
from vermilion.core.device.usb import UsbDevice

DEMO_DIR = Path(__file__).parents[1].joinpath("demo")
DEMOS = sorted(DEMO_DIR.glob("*.state"))


def load(path: Path) -> Card:
    card = sim.load_card(path)
    card.setup()
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)
    return card


def values(sections: list[Section]) -> dict[str, dict[str, str]]:
    return {s.title: {r.label: r.value for r in s.rows} for s in sections}


@pytest.mark.parametrize("path", DEMOS, ids=lambda p: p.name)
def test_card_sections(path: Path) -> None:
    info = values(DeviceInfo(load(path)).sections)
    assert info["Interface"]["Simulated"]
    assert info["Driver and Firmware"]["Driver"] == "none (simulated)"
    assert "USB" not in info


def test_gen4_18i20() -> None:
    info = values(DeviceInfo(load(DEMO_DIR.joinpath("Scarlett Gen 4 18i20.state"))).sections)
    io = info["Inputs and Outputs"]
    assert io["Analogue"] == "9 inputs, 14 outputs"
    assert io["Computer (PCM)"] == "26 capture, 26 playback channels"
    assert info["Features"]["Talkback"] == "yes"


def test_section_skips_missing_values() -> None:
    section = Section("S")
    section.add("a", None)
    section.add("b", "")
    section.add("c", 0)
    assert section.rows == [Row("c", "0")]


def test_as_text() -> None:
    info = DeviceInfo(None)
    info.sections = [Section("A", [Row("x", "1")]), Section("B")]
    assert info.as_text() == "A:\n  x: 1\n\nB:\n"


def _usb_device(
    root: Path, name: str, vid: str, pid: str, serial: str, card: int | None = None
) -> None:
    device = root / name
    device.mkdir(parents=True)
    for attr, value in {
        "idVendor": vid,
        "idProduct": pid,
        "product": "Scarlett",
        "manufacturer": "Focusrite",
        "serial": serial,
        "bcdDevice": "0645",
        "speed": "480",
        "version": " 2.00",
    }.items():
        (device / attr).write_text(value + "\n")
    interface = device / f"{name}:1.0"
    interface.mkdir()
    if card is not None:
        (interface / "sound" / f"card{card}").mkdir(parents=True)


def usb_rows() -> list[Row]:
    info = DeviceInfo(None)
    return next(s for s in info.sections if s.title == "Focusrite USB Devices").rows


def test_usb_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "usb"
    _usb_device(root, "3-1", "1235", "8214", "A1", card=0)
    _usb_device(root, "3-2", "1235", "821d", "B2", card=4)
    _usb_device(root, "3-3", "1235", "8215", "C3")  # no driver
    _usb_device(root, "3-4", "1235", "9999", "D4")  # unknown model
    _usb_device(root, "3-5", "046d", "0843", "E5")  # not Focusrite
    (root / "3-1:1.0").mkdir()  # interfaces are no devices
    (root / "usb3").mkdir()
    monkeypatch.setattr(usb, "USB_DEVICES", root)

    devices = UsbDevice.all()
    assert [d.serial for d in devices] == ["A1", "B2", "C3", "D4"]
    assert devices[0].model == "Scarlett 18i8 3rd Gen"
    assert devices[0].release == "6.45"
    assert devices[0].speed_mbps == 480
    assert devices[1].alsa_cards == (4,)

    rows = {r.value.split(" · ")[0]: r.value for r in usb_rows()}
    assert rows["A1"].endswith("ALSA card 0")
    assert rows["B2"].endswith("ALSA card 4")
    assert "no ALSA sound card" in rows["C3"]
    assert rows["D4"].endswith("not supported")


def test_no_usb_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(usb, "USB_DEVICES", tmp_path)
    assert [r.label for r in usb_rows()] == ["None found"]

# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""A card found by ALSA: its elements are read from the control device,
and follow its events."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Self

from gi.repository import GLib

from vermilion.core import asound
from vermilion.core.asound import (
    ELEM_TYPE_BOOLEAN,
    ELEM_TYPE_BYTES,
    ELEM_TYPE_ENUMERATED,
    ELEM_TYPE_INTEGER,
)
from vermilion.core.card.card import Card
from vermilion.core.card.elem import AlsaElem, Elem
from vermilion.core.products import FOCUSRITE_VID

_log = logging.getLogger(__name__)


class AlsaCard(Card):
    """An interface found by ALSA: its elements are read from the control
    device, and follow its events."""

    def __init__(self, num: int, device: str, name: str, ctl: asound.Ctl) -> None:
        super().__init__(num)
        self.device = device
        self.name = name
        self.ctl: asound.Ctl | None = ctl
        self._watch_id = 0
        self._read_identity()

    def _read_identity(self) -> None:
        """The USB product ID and the serial number."""
        path = Path("/proc/asound").joinpath(f"card{self.num}", "usbid")
        try:
            vid_s, pid_s = path.read_text().strip().split(":")
            vid, pid = int(vid_s, 16), int(pid_s, 16)
        except (OSError, ValueError) as e:
            _log.warning(f"can't read {path}: {e}")
        else:
            if vid == FOCUSRITE_VID:
                self.pid = pid
            else:
                _log.warning(f"VID {vid:04x} != expected 0x1235 for Focusrite")

        # controlC<N>/device is the sound card, whose device is the USB
        # interface; its parent is the USB device with the serial file
        path = Path("/sys/class/sound").joinpath(
            f"controlC{self.num}", "device", "device", "..", "serial"
        )
        try:
            serial = path.read_text().split()
        except OSError as e:
            _log.warning(f"can't open {path}: {e}")
            return
        if serial:
            self.serial = serial[0][:39]

    @property
    def is_open(self) -> bool:
        return self.ctl is not None

    def control(self) -> asound.Ctl:
        """The open control device."""
        assert self.ctl is not None, f"{self.name}: control device is not open"
        return self.ctl

    def watch(self, callback: Callable[[Self], bool]) -> None:
        """Call callback when the control device has events, until it
        returns False."""

        def ready(_channel: GLib.IOChannel, _condition: GLib.IOCondition) -> bool:
            if callback(self):
                return GLib.SOURCE_CONTINUE
            self._watch_id = 0
            return GLib.SOURCE_REMOVE

        fd = self.control().subscribe()
        self._watch_id = GLib.io_add_watch(
            GLib.IOChannel.unix_new(fd),
            GLib.PRIORITY_DEFAULT,
            GLib.IOCondition.IN | GLib.IOCondition.ERR | GLib.IOCondition.HUP,
            ready,
        )

    def destroy(self) -> None:
        if self._watch_id:
            GLib.source_remove(self._watch_id)
            self._watch_id = 0
        super().destroy()
        if self.ctl:
            self.ctl.close()
            self.ctl = None

    # loading the elements

    def _read_elem_tlv(self, elem: Elem, info: asound.ElemInfo) -> None:
        if elem.type != ELEM_TYPE_INTEGER or not info["tlv_readable"]:
            return

        buf, err = self.control().read_tlv(elem.numid)
        if buf is None:
            _log.warning(f"TLV read error: {asound.strerror(err)}")
            return

        tlv_type, tlv_len = buf[0], buf[1]

        # meter labels
        if tlv_type == asound.TLVT_FCP_CHANNEL_LABELS:
            raw = bytes(buf)[8 : 8 + tlv_len]
            labels = raw.split(b"\0")
            if len(labels) - 1 < elem.count:
                _log.warning(f"TLV label count {len(labels) - 1} < {elem.count}")
                return
            elem.meter_labels = [lbl.decode(errors="replace") for lbl in labels[: elem.count]]

        # dB range
        else:
            try:
                elem.db = asound.DbTlv(list(buf), info["min"], info["max"])
            except asound.AlsaError as e:
                _log.warning(str(e))
                return
            elem.min_val = info["min"]
            elem.max_val = info["max"]

    def _load_elem(self, numid: int) -> None:
        info = self.control().info(numid)
        if info is None:
            return

        if info["type"] not in (
            ELEM_TYPE_BOOLEAN,
            ELEM_TYPE_ENUMERATED,
            ELEM_TYPE_INTEGER,
            ELEM_TYPE_BYTES,
        ):
            return

        name = info["name"]
        if "Validity" in name or "Channel Map" in name:
            return

        template = AlsaElem(self, numid, name, info["type"], info["count"], 0)
        self._read_elem_tlv(template, info)

        # integer range if not set by TLV
        if template.type == ELEM_TYPE_INTEGER and template.min_val >= template.max_val:
            template.min_val = info["min"]
            template.max_val = info["max"]

        # Scarlett 1st Gen driver puts two volume controls/mutes in the
        # same element, so split them out to match the other series
        count = template.count
        if name == "Level Meter" or count > 2:
            count = 1

        for i in range(count):
            elem = AlsaElem(self, numid, name, template.type, template.count, i)
            for attr in ("min_val", "max_val", "db", "meter_labels"):
                setattr(elem, attr, getattr(template, attr))

            # initialise the value cache for change detection
            if elem.type == ELEM_TYPE_BYTES:
                pass
            elif elem.count == 1:
                elem.value = elem.get_value()
            elif elem.count > 1:
                elem.values = elem.get_int_values()

            self.add_elem(elem)

    def load_elems(self) -> None:
        for numid in self.control().elem_numids():
            self._load_elem(numid)

    # events

    def handle_events(self) -> bool:
        """Process pending ALSA events; return False if the self went away."""
        if not self.ctl:
            return False

        events, err = self.ctl.read_events()

        for numid, mask in events:
            if mask == asound.EVENT_MASK_REMOVE:
                return False

            if not mask & (asound.EVENT_MASK_VALUE | asound.EVENT_MASK_INFO):
                continue

            for elem in [e for e in self.elems if e.numid == numid]:
                if elem.simulated:
                    continue
                if elem.type == ELEM_TYPE_BYTES:
                    value_changed = True
                elif elem.count == 1:
                    new_value = elem.get_value()
                    value_changed = new_value != elem.value
                    elem.value = new_value
                elif elem.count > 1:
                    new_values = elem.get_int_values()
                    value_changed = new_values != elem.values
                    elem.values = new_values
                else:
                    value_changed = True

                # info events (writable/range changes) always need a callback;
                # value-only events only when the value changed
                if value_changed or mask & asound.EVENT_MASK_INFO:
                    _log.debug("event: %s changed", elem.name)
                    elem.emit_changed()

        if err == -19:  # ENODEV
            return False
        if err < 0:
            _log.warning(f"card_callback_error {err}")

        return True

# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""ALSA elements (controls): backed by a real control of the device
(AlsaElem), or holding their state themselves (SimElem, for simulated
cards loaded from .state files, and for "optional" controls such as
custom names that the driver doesn't provide but which are persisted
in the state file instead)."""

import logging
from typing import TYPE_CHECKING, ClassVar

from gi.repository import GLib, GObject

from vermilion.core import asound
from vermilion.core.asound import (
    ELEM_TYPE_BOOLEAN,
    ELEM_TYPE_BYTES,
    ELEM_TYPE_ENUMERATED,
    ELEM_TYPE_INTEGER,
)
from vermilion.core.constants import (
    HW,
    PC,
)
from vermilion.core.signals import SignalSpec, signal
from vermilion.core.util import bytes_to_str, c_round, get_num_from_string, parse_int_prefix

if TYPE_CHECKING:
    from vermilion.core.card.alsa import AlsaCard
    from vermilion.core.card.card import Card

_log = logging.getLogger(__name__)


class Elem(GObject.Object):
    """An ALSA control element (or one value of a multi-value element).

    AlsaElem is backed by a control of the device, SimElem holds its state
    itself. Emits "changed" when the value changes.
    """

    __gsignals__: ClassVar[dict[str, SignalSpec]] = {"changed": signal()}

    simulated: ClassVar[bool]
    # created by the application for a control the driver doesn't provide
    optional = False

    def __init__(
        self,
        card: Card,
        numid: int = 0,
        name: str = "",
        elem_type: int = 0,
        count: int = 1,
        index: int = 0,
    ) -> None:
        super().__init__()
        self.card = card
        self.numid = numid
        self.name = name
        self.type = elem_type
        self.count = count
        self.index = index

        # for gain/volume elements, the value range and the dB information
        # (asound.DbTlv)
        self.min_val = 0
        self.max_val = 0
        self.db: asound.DbTlv | None = None

        # level meter labels (from the FCP driver TLV)
        self.meter_labels: list[str] | None = None

        # for routing sinks
        self.port_category = PC.OFF
        self.port_num = 0
        self.hw_type = HW.ANALOGUE
        self.lr_num = 0

        # the value (the state of a simulated element, the cache for change
        # detection of a real one)
        self.value = 0
        self.values: list[int] | None = None
        self.bytes_value = b""

        self._pending_idle = 0

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.numid} {self.name!r}>"

    @property
    def db_type(self) -> int:
        return self.db.type if self.db else 0

    @property
    def min_cdb(self) -> int:
        return self.db.min_cdb if self.db else 0

    @property
    def max_cdb(self) -> int:
        return self.db.max_cdb if self.db else 0

    # dB (the conversion is done by alsa-lib, see asound.DbTlv)

    @property
    def is_linear(self) -> bool:
        return self.db_type == asound.TLVT_DB_LINEAR

    def gain_db(self, value: int) -> float:
        """Gain in dB of a value (-inf/mute as the minimum)."""
        if not self.db:
            return 0.0
        return self.db.to_cdb(value) / 100.0

    def value_to_db(self, value: int) -> float:
        """dB value of a value, clamped to the dB range."""
        min_db = c_round(self.min_cdb / 100.0)
        max_db = c_round(self.max_cdb / 100.0)
        return max(min_db, min(max_db, self.gain_db(value)))

    def db_to_value(self, db: float) -> int:
        """Value closest to a dB value."""
        if not self.db:
            return self.min_val
        cdb = c_round(db * 100)
        lo = self.db.from_cdb(cdb, 0)
        hi = self.db.from_cdb(cdb, 1)
        # alsa-lib rounds down or up; take the nearer one
        if abs(self.db.to_cdb(hi) - cdb) < abs(self.db.to_cdb(lo) - cdb):
            return hi
        return lo

    # values

    def get_value(self) -> int:
        """Boolean, enum, or int value (of this element's index)."""
        raise NotImplementedError

    def set_value(self, value: int) -> None:
        raise NotImplementedError

    def get_int_values(self) -> list[int]:
        raise NotImplementedError

    def set_int_values(self, values: list[int]) -> None:
        values = [int(v) for v in values[: self.count]]

        if self.values is None:
            self.values = [0] * self.count

        # skip if unchanged
        if self.values[: len(values)] == values:
            return
        self._write_int_values(values)

    def _write_int_values(self, values: list[int]) -> None:
        raise NotImplementedError

    def get_bytes(self) -> bytes:
        raise NotImplementedError

    def set_bytes(self, data: str | bytes) -> None:
        raise NotImplementedError

    def get_str(self) -> str:
        """BYTES element value as a string ("" if empty or invalid)."""
        return bytes_to_str(self.get_bytes())

    # info

    def writable(self) -> bool:
        raise NotImplementedError

    def volatile(self) -> bool:
        raise NotImplementedError

    def items(self) -> list[str]:
        """List of enum item names."""
        raise NotImplementedError

    def item_count(self) -> int:
        return len(self.items())

    def item_name(self, i: int) -> str:
        items = self.items()
        return items[i] if 0 <= i < len(items) else ""

    # as text (in configuration files)

    @property
    def persistent(self) -> bool:
        """Saved in configurations: not volatile (level meters) nor
        read-only (status)."""
        return not self.volatile() and self.writable()

    def to_string(self) -> str | None:
        t = self.type
        if t == ELEM_TYPE_BOOLEAN:
            return "true" if self.get_value() else "false"
        if t == ELEM_TYPE_ENUMERATED:
            return self.item_name(self.get_value())
        if t == ELEM_TYPE_INTEGER:
            if self.count <= 1:
                return str(self.get_value())
            return ",".join(str(v) for v in self.get_int_values())
        if t == ELEM_TYPE_BYTES:
            return bytes(self.get_bytes()).split(b"\0", 1)[0].decode("utf-8", errors="replace")
        return None

    def set_from_string(self, text: str) -> None:
        t = self.type

        # multi-valued integers are comma-separated
        if t == ELEM_TYPE_INTEGER and self.count > 1:
            values: list[int] = []
            rest = text
            while rest and len(values) < self.count:
                v, rest = parse_int_prefix(rest)
                if v is None:
                    break
                values.append(v)
                rest = rest.removeprefix(",")
            if values:
                self.set_int_values(values)
                self.emit_changed()
            return

        # bytes are used for custom names
        if t == ELEM_TYPE_BYTES:
            self.set_bytes(text)
            return

        if t == ELEM_TYPE_BOOLEAN:
            value = 1 if text in ("true", "1") else 0
        elif t == ELEM_TYPE_ENUMERATED:
            items = self.items()
            if text in items:
                value = items.index(text)
            else:
                parsed, rest = parse_int_prefix(text)
                if parsed is None or rest:
                    return
                value = parsed
        elif t == ELEM_TYPE_INTEGER:
            parsed, rest = parse_int_prefix(text)
            if parsed is None or (rest and not rest.startswith(",")):
                return
            value = parsed
        else:
            return

        self.set_value(value)
        # trigger callbacks to update the UI immediately
        self.emit_changed()

    # routing

    def parse_lr_num(self) -> None:
        """The channel number from the name ("Master 2L", "Analogue 3 ...")."""
        name = self.name
        if name.startswith(("Master Playback", "Master HW Playback")):
            self.lr_num = 0
        elif name.startswith("Master"):
            # "Master %d%c"
            rest = name[len("Master ") :] if name.startswith("Master ") else ""
            digits = ""
            for ch in rest:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if not digits or len(rest) <= len(digits):
                _log.warning(f"can't parse Master '{name}'")
                return
            side = rest[len(digits)]
            self.lr_num = int(digits) * 2 - (1 if side in ("L", " ") else 0) + self.index
        else:
            self.lr_num = get_num_from_string(name)

    @property
    def value_text(self) -> str:
        """The value for display: an enum item, on/off or a number."""
        if self.type == ELEM_TYPE_ENUMERATED:
            return self.item_name(self.get_value())
        if self.type == ELEM_TYPE_BOOLEAN:
            return "on" if self.get_value() else "off"
        return str(self.get_value())

    # change notification

    def emit_changed(self) -> None:
        self.emit("changed")

    def _idle_emit_changed(self) -> bool:
        self._pending_idle = 0
        self.emit_changed()
        return GLib.SOURCE_REMOVE

    def emit_changed_idle(self) -> None:
        if not self._pending_idle:
            self._pending_idle = GLib.idle_add(self._idle_emit_changed)

    def cancel_idle(self) -> None:
        if self._pending_idle:
            GLib.source_remove(self._pending_idle)
            self._pending_idle = 0


class AlsaElem(Elem):
    """An element backed by a control of the device.

    Writes don't update the value cache: the ALSA event does that (see
    handle_events), so that the callbacks fire.
    """

    simulated = False
    card: AlsaCard

    def __init__(
        self, card: AlsaCard, numid: int, name: str, elem_type: int, count: int, index: int
    ) -> None:
        super().__init__(card, numid, name, elem_type, count, index)
        self._item_names: list[str] | None = None

    @property
    def ctl(self) -> asound.Ctl:
        return self.card.control()

    def _is_scalar(self) -> bool:
        if self.type in (ELEM_TYPE_BOOLEAN, ELEM_TYPE_ENUMERATED, ELEM_TYPE_INTEGER):
            return True
        _log.error(
            "element %s (%d) has type %d, not bool/enum/int", self.name, self.numid, self.type
        )
        return False

    def get_value(self) -> int:
        if not self._is_scalar():
            return 0
        return self.ctl.read_value(self.numid, self.type, self.index)

    def set_value(self, value: int) -> None:
        if self._is_scalar():
            _log.debug("write %s = %d", self.name, value)
            self.ctl.write_value(self.numid, self.type, self.index, int(value))

    def get_int_values(self) -> list[int]:
        return self.ctl.read_int_values(self.numid, self.count)

    def _write_int_values(self, values: list[int]) -> None:
        _log.debug("write %s = %s", self.name, values)
        self.ctl.write_int_values(self.numid, values)

    def get_bytes(self) -> bytes:
        self.bytes_value = self.ctl.read_bytes(self.numid, self.count)
        return self.bytes_value

    def set_bytes(self, data: str | bytes) -> None:
        if isinstance(data, str):
            data = data.encode()
        _log.debug("write %s = %r", self.name, data)
        self.ctl.write_bytes(self.numid, data)

    def writable(self) -> bool:
        return self.ctl.is_writable(self.numid)

    def volatile(self) -> bool:
        return self.ctl.is_volatile(self.numid)

    def items(self) -> list[str]:
        if self._item_names is None:
            n = self.ctl.item_count(self.numid)
            self._item_names = [self.ctl.item_name(self.numid, i) for i in range(n)]
        return self._item_names


class SimElem(Elem):
    """An element holding its state itself: the elements of simulated
    cards (loaded from .state files) and "optional" controls, such as
    custom names, that the driver doesn't provide but which are persisted
    in the state file instead."""

    simulated = True

    def __init__(
        self,
        card: Card,
        numid: int = 0,
        name: str = "",
        elem_type: int = 0,
        count: int = 1,
        index: int = 0,
    ) -> None:
        super().__init__(card, numid, name, elem_type, count, index)
        self.is_writable = False
        self.is_volatile = False
        self.item_names: list[str] | None = None
        # maximum length of a BYTES element
        self.bytes_size = 0

    def get_value(self) -> int:
        return self.value

    def set_value(self, value: int) -> None:
        value = int(value)
        if self.value != value:
            self.value = value
            self.emit_changed()

    def get_int_values(self) -> list[int]:
        vals = list(self.values or [])
        return (vals + [0] * self.count)[: self.count]

    def _write_int_values(self, values: list[int]) -> None:
        assert self.values is not None
        self.values[: len(values)] = values
        self.emit_changed_idle()

    def get_bytes(self) -> bytes:
        return self.bytes_value[: self.count]

    def set_bytes(self, data: str | bytes) -> None:
        if isinstance(data, str):
            data = data.encode()
        data = data[: self.bytes_size]
        if self.count == len(data) and self.bytes_value[: len(data)] == data:
            return
        self.bytes_value = data
        self.count = len(data)
        self.emit_changed_idle()

    def writable(self) -> bool:
        return self.is_writable

    def volatile(self) -> bool:
        return self.is_volatile

    def items(self) -> list[str]:
        return list(self.item_names or [])

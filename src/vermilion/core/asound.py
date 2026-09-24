# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Minimal ctypes bindings for the parts of libasound we need.

Covers the control interface (element list/info/value/TLV/events),
the hwdep interface (Scarlett2 driver ioctls) and the configuration
parser (for alsactl .state files).
"""

import ctypes
import os
from collections.abc import Callable, Iterator
from ctypes import (
    POINTER,
    byref,
    c_char_p,
    c_int,
    c_long,
    c_short,
    c_size_t,
    c_uint,
    c_void_p,
)
from pathlib import Path
from typing import Any, Self, TypedDict

_lib = ctypes.CDLL("libasound.so.2", use_errno=True)

# element types
ELEM_TYPE_BOOLEAN = 1
ELEM_TYPE_INTEGER = 2
ELEM_TYPE_ENUMERATED = 3
ELEM_TYPE_BYTES = 4

ELEM_IFACE_CARD = 0

EVENT_ELEM = 0
EVENT_MASK_VALUE = 1 << 0
EVENT_MASK_INFO = 1 << 1
EVENT_MASK_REMOVE = 0xFFFFFFFF

HWDEP_OPEN_DUPLEX = os.O_RDWR

# TLV
TLVT_DB_SCALE = 1
TLVT_DB_LINEAR = 2
TLVT_DB_RANGE = 3
TLVT_DB_MINMAX = 4
TLVT_DB_MINMAX_MUTE = 5
TLVT_FCP_CHANNEL_LABELS = 0x110
MAX_TLV_RANGE_SIZE = 1024

# snd_config types
CONFIG_TYPE_INTEGER = 0
CONFIG_TYPE_STRING = 3
CONFIG_TYPE_COMPOUND = 1024


class _PollFd(ctypes.Structure):
    _fields_ = [("fd", c_int), ("events", c_short), ("revents", c_short)]


def _fn(name: str, restype: Any, *argtypes: Any) -> Callable[..., Any]:
    f = getattr(_lib, name)
    f.restype = restype
    f.argtypes = argtypes
    fn: Callable[..., Any] = f
    return fn


P = c_void_p
PP = POINTER(c_void_p)

snd_strerror = _fn("snd_strerror", c_char_p, c_int)
snd_asoundlib_version = _fn("snd_asoundlib_version", c_char_p)
snd_card_next = _fn("snd_card_next", c_int, POINTER(c_int))

snd_ctl_open = _fn("snd_ctl_open", c_int, PP, c_char_p, c_int)
snd_ctl_close = _fn("snd_ctl_close", c_int, P)
snd_ctl_nonblock = _fn("snd_ctl_nonblock", c_int, P, c_int)
snd_ctl_subscribe_events = _fn("snd_ctl_subscribe_events", c_int, P, c_int)
snd_ctl_poll_descriptors_count = _fn("snd_ctl_poll_descriptors_count", c_int, P)
snd_ctl_poll_descriptors = _fn("snd_ctl_poll_descriptors", c_int, P, POINTER(_PollFd), c_uint)

snd_ctl_card_info_malloc = _fn("snd_ctl_card_info_malloc", c_int, PP)
snd_ctl_card_info_free = _fn("snd_ctl_card_info_free", None, P)
snd_ctl_card_info = _fn("snd_ctl_card_info", c_int, P, P)
snd_ctl_card_info_get_name = _fn("snd_ctl_card_info_get_name", c_char_p, P)

snd_ctl_elem_list_malloc = _fn("snd_ctl_elem_list_malloc", c_int, PP)
snd_ctl_elem_list_free = _fn("snd_ctl_elem_list_free", None, P)
snd_ctl_elem_list = _fn("snd_ctl_elem_list", c_int, P, P)
snd_ctl_elem_list_get_count = _fn("snd_ctl_elem_list_get_count", c_uint, P)
snd_ctl_elem_list_alloc_space = _fn("snd_ctl_elem_list_alloc_space", c_int, P, c_uint)
snd_ctl_elem_list_free_space = _fn("snd_ctl_elem_list_free_space", None, P)
snd_ctl_elem_list_get_numid = _fn("snd_ctl_elem_list_get_numid", c_uint, P, c_uint)

snd_ctl_elem_id_malloc = _fn("snd_ctl_elem_id_malloc", c_int, PP)
snd_ctl_elem_id_free = _fn("snd_ctl_elem_id_free", None, P)
snd_ctl_elem_id_set_numid = _fn("snd_ctl_elem_id_set_numid", None, P, c_uint)
snd_ctl_elem_id_set_interface = _fn("snd_ctl_elem_id_set_interface", None, P, c_int)
snd_ctl_elem_id_set_name = _fn("snd_ctl_elem_id_set_name", None, P, c_char_p)

snd_ctl_elem_info_malloc = _fn("snd_ctl_elem_info_malloc", c_int, PP)
snd_ctl_elem_info_free = _fn("snd_ctl_elem_info_free", None, P)
snd_ctl_elem_info_clear = _fn("snd_ctl_elem_info_clear", None, P)
snd_ctl_elem_info = _fn("snd_ctl_elem_info", c_int, P, P)
snd_ctl_elem_info_set_numid = _fn("snd_ctl_elem_info_set_numid", None, P, c_uint)
snd_ctl_elem_info_set_id = _fn("snd_ctl_elem_info_set_id", None, P, P)
snd_ctl_elem_info_set_item = _fn("snd_ctl_elem_info_set_item", None, P, c_uint)
snd_ctl_elem_info_get_type = _fn("snd_ctl_elem_info_get_type", c_int, P)
snd_ctl_elem_info_get_name = _fn("snd_ctl_elem_info_get_name", c_char_p, P)
snd_ctl_elem_info_get_count = _fn("snd_ctl_elem_info_get_count", c_uint, P)
snd_ctl_elem_info_get_min = _fn("snd_ctl_elem_info_get_min", c_long, P)
snd_ctl_elem_info_get_max = _fn("snd_ctl_elem_info_get_max", c_long, P)
snd_ctl_elem_info_get_items = _fn("snd_ctl_elem_info_get_items", c_uint, P)
snd_ctl_elem_info_get_item_name = _fn("snd_ctl_elem_info_get_item_name", c_char_p, P)
snd_ctl_elem_info_is_writable = _fn("snd_ctl_elem_info_is_writable", c_int, P)
snd_ctl_elem_info_is_locked = _fn("snd_ctl_elem_info_is_locked", c_int, P)
snd_ctl_elem_info_is_volatile = _fn("snd_ctl_elem_info_is_volatile", c_int, P)
snd_ctl_elem_info_is_tlv_readable = _fn("snd_ctl_elem_info_is_tlv_readable", c_int, P)

snd_ctl_elem_value_malloc = _fn("snd_ctl_elem_value_malloc", c_int, PP)
snd_ctl_elem_value_free = _fn("snd_ctl_elem_value_free", None, P)
snd_ctl_elem_value_clear = _fn("snd_ctl_elem_value_clear", None, P)
snd_ctl_elem_value_set_numid = _fn("snd_ctl_elem_value_set_numid", None, P, c_uint)
snd_ctl_elem_read = _fn("snd_ctl_elem_read", c_int, P, P)
snd_ctl_elem_write = _fn("snd_ctl_elem_write", c_int, P, P)
snd_ctl_elem_value_get_boolean = _fn("snd_ctl_elem_value_get_boolean", c_int, P, c_uint)
snd_ctl_elem_value_get_integer = _fn("snd_ctl_elem_value_get_integer", c_long, P, c_uint)
snd_ctl_elem_value_get_enumerated = _fn("snd_ctl_elem_value_get_enumerated", c_uint, P, c_uint)
snd_ctl_elem_value_set_boolean = _fn("snd_ctl_elem_value_set_boolean", None, P, c_uint, c_long)
snd_ctl_elem_value_set_integer = _fn("snd_ctl_elem_value_set_integer", None, P, c_uint, c_long)
snd_ctl_elem_value_set_enumerated = _fn(
    "snd_ctl_elem_value_set_enumerated", None, P, c_uint, c_uint
)
snd_ctl_elem_value_get_bytes = _fn("snd_ctl_elem_value_get_bytes", c_void_p, P)
snd_ctl_elem_set_bytes = _fn("snd_ctl_elem_set_bytes", None, P, c_void_p, c_size_t)

snd_ctl_elem_tlv_read = _fn("snd_ctl_elem_tlv_read", c_int, P, P, POINTER(c_uint), c_uint)
snd_tlv_parse_dB_info = _fn(
    "snd_tlv_parse_dB_info", c_int, POINTER(c_uint), c_uint, POINTER(POINTER(c_uint))
)
snd_tlv_get_dB_range = _fn(
    "snd_tlv_get_dB_range", c_int, POINTER(c_uint), c_long, c_long, POINTER(c_long), POINTER(c_long)
)
snd_tlv_convert_to_dB = _fn(
    "snd_tlv_convert_to_dB", c_int, POINTER(c_uint), c_long, c_long, c_long, POINTER(c_long)
)
snd_tlv_convert_from_dB = _fn(
    "snd_tlv_convert_from_dB",
    c_int,
    POINTER(c_uint),
    c_long,
    c_long,
    c_long,
    POINTER(c_long),
    c_int,
)

snd_ctl_event_malloc = _fn("snd_ctl_event_malloc", c_int, PP)
snd_ctl_event_free = _fn("snd_ctl_event_free", None, P)
snd_ctl_read = _fn("snd_ctl_read", c_int, P, P)
snd_ctl_event_get_type = _fn("snd_ctl_event_get_type", c_int, P)
snd_ctl_event_elem_get_numid = _fn("snd_ctl_event_elem_get_numid", c_uint, P)
snd_ctl_event_elem_get_mask = _fn("snd_ctl_event_elem_get_mask", c_uint, P)

snd_hwdep_open = _fn("snd_hwdep_open", c_int, PP, c_char_p, c_int)
snd_hwdep_close = _fn("snd_hwdep_close", c_int, P)
snd_hwdep_ioctl = _fn("snd_hwdep_ioctl", c_int, P, c_uint, c_void_p)

snd_config_top = _fn("snd_config_top", c_int, PP)
snd_config_delete = _fn("snd_config_delete", c_int, P)
snd_config_load = _fn("snd_config_load", c_int, P, P)
snd_input_stdio_open = _fn("snd_input_stdio_open", c_int, PP, c_char_p, c_char_p)
snd_input_close = _fn("snd_input_close", c_int, P)
snd_config_iterator_first = _fn("snd_config_iterator_first", c_void_p, P)
snd_config_iterator_next = _fn("snd_config_iterator_next", c_void_p, P)
snd_config_iterator_end = _fn("snd_config_iterator_end", c_void_p, P)
snd_config_iterator_entry = _fn("snd_config_iterator_entry", c_void_p, P)
snd_config_get_id = _fn("snd_config_get_id", c_int, P, POINTER(c_char_p))
snd_config_get_type = _fn("snd_config_get_type", c_int, P)
snd_config_get_string = _fn("snd_config_get_string", c_int, P, POINTER(c_char_p))
snd_config_get_integer = _fn("snd_config_get_integer", c_int, P, POINTER(c_long))
snd_config_is_array = _fn("snd_config_is_array", c_int, P)


class ElemInfo(TypedDict):
    type: int
    name: str
    count: int
    min: int
    max: int
    items: int
    writable: bool
    locked: bool
    volatile: bool
    tlv_readable: bool


class AlsaError(Exception):
    def __init__(self, what: str, err: int) -> None:
        super().__init__(f"{what}: {strerror(err)}")
        self.err = err


def strerror(err: int) -> str:
    return str(snd_strerror(err).decode(errors="replace"))


def library_version() -> str:
    """Version of the loaded alsa-lib."""
    return _dec(snd_asoundlib_version())


def _dec(b: bytes | None) -> str:
    return b.decode("utf-8", errors="replace") if b is not None else ""


def _alloc(malloc: Callable[..., Any]) -> c_void_p:
    p = c_void_p()
    err = malloc(byref(p))
    if err < 0:
        raise AlsaError("malloc", err)
    return p


def card_next(num: int) -> int:
    n = c_int(num)
    err = snd_card_next(byref(n))
    if err < 0:
        raise AlsaError("snd_card_next", err)
    return n.value


def card_numbers() -> Iterator[int]:
    num = -1
    while True:
        num = card_next(num)
        if num < 0:
            return
        yield num


class Ctl:
    """An open ALSA control device (hw:N) with reusable scratch objects."""

    def __init__(self, device: str) -> None:
        self.device = device
        self._handle = c_void_p()
        err = snd_ctl_open(byref(self._handle), device.encode(), 0)
        if err < 0:
            raise AlsaError(f"snd_ctl_open {device}", err)
        # scratch objects; None after close()
        self._info: c_void_p | None = _alloc(snd_ctl_elem_info_malloc)
        self._value: c_void_p | None = _alloc(snd_ctl_elem_value_malloc)
        self._id: c_void_p | None = _alloc(snd_ctl_elem_id_malloc)
        self._event: c_void_p | None = None

    @property
    def handle(self) -> c_void_p:
        return self._handle

    def close(self) -> None:
        if self._handle:
            snd_ctl_close(self._handle)
            self._handle = c_void_p()
        for p, free in (
            (self._info, snd_ctl_elem_info_free),
            (self._value, snd_ctl_elem_value_free),
            (self._id, snd_ctl_elem_id_free),
            (self._event, snd_ctl_event_free),
        ):
            if p:
                free(p)
        self._info = self._value = self._id = self._event = None

    def card_name(self) -> str:
        info = _alloc(snd_ctl_card_info_malloc)
        try:
            err = snd_ctl_card_info(self._handle, info)
            if err < 0:
                raise AlsaError("snd_ctl_card_info", err)
            return _dec(snd_ctl_card_info_get_name(info))
        finally:
            snd_ctl_card_info_free(info)

    def elem_numids(self) -> list[int]:
        lst = _alloc(snd_ctl_elem_list_malloc)
        try:
            snd_ctl_elem_list(self._handle, lst)
            count = snd_ctl_elem_list_get_count(lst)
            snd_ctl_elem_list_alloc_space(lst, count)
            snd_ctl_elem_list(self._handle, lst)
            numids = [int(snd_ctl_elem_list_get_numid(lst, i)) for i in range(count)]
            snd_ctl_elem_list_free_space(lst)
            return numids
        finally:
            snd_ctl_elem_list_free(lst)

    # element info

    def _load_info(self, numid: int, item: int | None = None) -> int:
        snd_ctl_elem_info_clear(self._info)
        snd_ctl_elem_info_set_numid(self._info, numid)
        if item is not None:
            snd_ctl_elem_info_set_item(self._info, item)
        return int(snd_ctl_elem_info(self._handle, self._info))

    def info(self, numid: int) -> ElemInfo | None:
        """Return a dict describing the element, or None on error."""
        if self._load_info(numid) < 0:
            return None
        i = self._info
        t = int(snd_ctl_elem_info_get_type(i))
        # the getters below assert on the element type
        is_int = t == ELEM_TYPE_INTEGER
        return {
            "type": t,
            "name": _dec(snd_ctl_elem_info_get_name(i)),
            "count": int(snd_ctl_elem_info_get_count(i)),
            "min": int(snd_ctl_elem_info_get_min(i)) if is_int else 0,
            "max": int(snd_ctl_elem_info_get_max(i)) if is_int else 0,
            "items": int(snd_ctl_elem_info_get_items(i)) if t == ELEM_TYPE_ENUMERATED else 0,
            "writable": bool(snd_ctl_elem_info_is_writable(i)),
            "locked": bool(snd_ctl_elem_info_is_locked(i)),
            "volatile": bool(snd_ctl_elem_info_is_volatile(i)),
            "tlv_readable": bool(snd_ctl_elem_info_is_tlv_readable(i)),
        }

    def info_by_name(self, name: str, iface: int = ELEM_IFACE_CARD) -> dict[str, bool] | None:
        snd_ctl_elem_id_set_interface(self._id, iface)
        snd_ctl_elem_id_set_name(self._id, name.encode())
        snd_ctl_elem_info_clear(self._info)
        snd_ctl_elem_info_set_id(self._info, self._id)
        if snd_ctl_elem_info(self._handle, self._info) < 0:
            return None
        i = self._info
        return {
            "tlv_readable": bool(snd_ctl_elem_info_is_tlv_readable(i)),
            "locked": bool(snd_ctl_elem_info_is_locked(i)),
        }

    def is_writable(self, numid: int) -> bool:
        if self._load_info(numid) < 0:
            return False
        return bool(
            snd_ctl_elem_info_is_writable(self._info)
            and not snd_ctl_elem_info_is_locked(self._info)
        )

    def is_volatile(self, numid: int) -> bool:
        if self._load_info(numid) < 0:
            return False
        return bool(snd_ctl_elem_info_is_volatile(self._info))

    def item_count(self, numid: int) -> int:
        if self._load_info(numid) < 0:
            return 0
        return int(snd_ctl_elem_info_get_items(self._info))

    def item_name(self, numid: int, item: int) -> str:
        if self._load_info(numid, item) < 0:
            return ""
        return _dec(snd_ctl_elem_info_get_item_name(self._info))

    def read_tlv(self, numid: int) -> tuple[ctypes.Array[c_uint] | None, int]:
        """Return (TLV data, 0) or (None, negative error code)."""
        buf = (c_uint * MAX_TLV_RANGE_SIZE)()
        snd_ctl_elem_id_set_numid(self._id, numid)
        err = snd_ctl_elem_tlv_read(self._handle, self._id, buf, ctypes.sizeof(buf))
        if err < 0:
            return None, int(err)
        return buf, 0

    # element values

    def _read(self, numid: int) -> int:
        snd_ctl_elem_value_clear(self._value)
        snd_ctl_elem_value_set_numid(self._value, numid)
        return int(snd_ctl_elem_read(self._handle, self._value))

    def read_value(self, numid: int, elem_type: int, index: int) -> int:
        self._read(numid)
        v = self._value
        if elem_type == ELEM_TYPE_BOOLEAN:
            return int(snd_ctl_elem_value_get_boolean(v, index))
        if elem_type == ELEM_TYPE_ENUMERATED:
            return int(snd_ctl_elem_value_get_enumerated(v, index))
        if elem_type == ELEM_TYPE_INTEGER:
            return int(snd_ctl_elem_value_get_integer(v, index))
        return 0

    def read_int_values(self, numid: int, count: int) -> list[int]:
        self._read(numid)
        return [int(snd_ctl_elem_value_get_integer(self._value, i)) for i in range(count)]

    def read_bytes(self, numid: int, count: int) -> bytes:
        self._read(numid)
        p = snd_ctl_elem_value_get_bytes(self._value)
        if not p:
            return b""
        return ctypes.string_at(p, count)

    def write_value(self, numid: int, elem_type: int, index: int, value: int) -> int:
        self._read(numid)
        v = self._value
        if elem_type == ELEM_TYPE_BOOLEAN:
            snd_ctl_elem_value_set_boolean(v, index, int(value))
        elif elem_type == ELEM_TYPE_ENUMERATED:
            snd_ctl_elem_value_set_enumerated(v, index, int(value))
        elif elem_type == ELEM_TYPE_INTEGER:
            snd_ctl_elem_value_set_integer(v, index, int(value))
        else:
            return -1
        return int(snd_ctl_elem_write(self._handle, v))

    def write_int_values(self, numid: int, values: list[int]) -> int:
        snd_ctl_elem_value_clear(self._value)
        snd_ctl_elem_value_set_numid(self._value, numid)
        for i, val in enumerate(values):
            snd_ctl_elem_value_set_integer(self._value, i, int(val))
        return int(snd_ctl_elem_write(self._handle, self._value))

    def write_bytes(self, numid: int, data: bytes) -> int:
        snd_ctl_elem_value_clear(self._value)
        snd_ctl_elem_value_set_numid(self._value, numid)
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        snd_ctl_elem_set_bytes(self._value, buf, len(data))
        return int(snd_ctl_elem_write(self._handle, self._value))

    # events

    def subscribe(self) -> int:
        """Subscribe to events; return the file descriptor to poll."""
        count = snd_ctl_poll_descriptors_count(self._handle)
        if count != 1:
            raise RuntimeError(f"poll descriptors {count} != 1")
        snd_ctl_subscribe_events(self._handle, 1)
        snd_ctl_nonblock(self._handle, 1)
        pfd = _PollFd()
        snd_ctl_poll_descriptors(self._handle, byref(pfd), 1)
        self._event = _alloc(snd_ctl_event_malloc)
        return int(pfd.fd)

    def read_events(self) -> tuple[list[tuple[int, int]], int]:
        """Drain pending events.

        Returns (events, err) where events is a list of (numid, mask)
        tuples for element events and err is a negative error code (0 if
        all pending events were read successfully).
        """
        events: list[tuple[int, int]] = []
        while True:
            err = int(snd_ctl_read(self._handle, self._event))
            if err == 0 or err == -11:  # EAGAIN
                return events, 0
            if err < 0:
                return events, err
            if snd_ctl_event_get_type(self._event) != EVENT_ELEM:
                continue
            events.append(
                (
                    int(snd_ctl_event_elem_get_numid(self._event)),
                    int(snd_ctl_event_elem_get_mask(self._event)),
                )
            )


class DbTlv:
    """The dB information (TLV) of a volume element, converting between
    element values and dB with alsa-lib."""

    def __init__(self, words: list[int], min_val: int, max_val: int) -> None:
        """words: the TLV as unsigned ints; raises AlsaError."""
        self._buf = (c_uint * len(words))(*(w & 0xFFFFFFFF for w in words))
        self._rec = POINTER(c_uint)()
        ret = int(snd_tlv_parse_dB_info(self._buf, ctypes.sizeof(self._buf), byref(self._rec)))
        if ret <= 0:
            raise AlsaError("TLV parse error", ret)
        self.min_val = min_val
        self.max_val = max_val
        mn = c_long()
        mx = c_long()
        ret = int(snd_tlv_get_dB_range(self._rec, min_val, max_val, byref(mn), byref(mx)))
        if ret != 0:
            raise AlsaError("TLV range error", ret)
        self.type: int = self._rec[0]
        self.min_cdb: int = mn.value
        self.max_cdb: int = mx.value

    @classmethod
    def minmax(cls, min_cdb: int, max_cdb: int, min_val: int, max_val: int) -> Self:
        """dB range without a TLV (simulated elements): linear in dB."""
        return cls([TLVT_DB_MINMAX, 8, min_cdb, max_cdb], min_val, max_val)

    def to_cdb(self, value: int) -> int:
        cdb = c_long()
        if snd_tlv_convert_to_dB(self._rec, self.min_val, self.max_val, value, byref(cdb)) < 0:
            return self.min_cdb
        return cdb.value

    def from_cdb(self, cdb: int, xdir: int = 0) -> int:
        """Element value for a dB value; rounds up for xdir > 0."""
        value = c_long()
        if (
            snd_tlv_convert_from_dB(self._rec, self.min_val, self.max_val, cdb, byref(value), xdir)
            < 0
        ):
            return self.min_val
        return value.value


class Hwdep:
    """An open hwdep device, used for the Scarlett2 driver ioctls."""

    def __init__(self, handle: c_void_p) -> None:
        self._handle: c_void_p | None = handle

    @classmethod
    def open(cls, device: str) -> tuple[Self | None, int]:
        """Open device; return (Hwdep, 0) or (None, negative errno)."""
        handle = c_void_p()
        err = snd_hwdep_open(byref(handle), device.encode(), HWDEP_OPEN_DUPLEX)
        if err < 0:
            return None, int(err)
        return cls(handle), 0

    def ioctl(self, request: int, arg: ctypes.Structure | c_int | None = None) -> int:
        return int(
            snd_hwdep_ioctl(
                self._handle,
                request,
                ctypes.cast(ctypes.pointer(arg), c_void_p) if arg is not None else None,
            )
        )

    def close(self) -> None:
        if self._handle:
            snd_hwdep_close(self._handle)
            self._handle = None


# configuration file parser (alsactl .state files)


class ConfigNode:
    """Read-only view of a snd_config_t node."""

    def __init__(self, ptr: c_void_p) -> None:
        self._ptr = ptr

    @property
    def id(self) -> str | None:
        s = c_char_p()
        err = snd_config_get_id(self._ptr, byref(s))
        if err < 0:
            raise AlsaError("snd_config_get_id", err)
        return _dec(s.value) if s.value is not None else None

    @property
    def type(self) -> int:
        return int(snd_config_get_type(self._ptr))

    def is_array(self) -> int:
        return int(snd_config_is_array(self._ptr))

    def string(self) -> str:
        s = c_char_p()
        err = snd_config_get_string(self._ptr, byref(s))
        if err < 0:
            raise AlsaError("snd_config_get_string", err)
        return _dec(s.value)

    def integer(self) -> int:
        v = c_long()
        err = snd_config_get_integer(self._ptr, byref(v))
        if err < 0:
            raise AlsaError("snd_config_get_integer", err)
        return v.value

    def children(self) -> Iterator[ConfigNode]:
        it = snd_config_iterator_first(self._ptr)
        end = snd_config_iterator_end(self._ptr)
        while it != end:
            nxt = snd_config_iterator_next(it)
            yield ConfigNode(c_void_p(snd_config_iterator_entry(it)))
            it = nxt


def load_config_file(path: Path) -> tuple[ConfigNode, Callable[[], object]]:
    """Load an alsa config file; return (top ConfigNode, free function)."""
    top = c_void_p()
    err = snd_config_top(byref(top))
    if err < 0:
        raise AlsaError("snd_config_top", err)
    inp = c_void_p()
    err = snd_input_stdio_open(byref(inp), os.fsencode(path), b"r")
    if err < 0:
        snd_config_delete(top)
        raise AlsaError(f"Error opening {path}", err)
    err = snd_config_load(top, inp)
    snd_input_close(inp)
    if err < 0:
        snd_config_delete(top)
        raise AlsaError("snd_config_load error", err)
    return ConfigNode(top), lambda: snd_config_delete(top)

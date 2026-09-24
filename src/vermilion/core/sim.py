# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Simulated cards created from alsactl .state files."""

import logging
import re
from pathlib import Path

from vermilion.core import asound
from vermilion.core.asound import (
    CONFIG_TYPE_COMPOUND,
    CONFIG_TYPE_INTEGER,
    CONFIG_TYPE_STRING,
    ELEM_TYPE_BOOLEAN,
    ELEM_TYPE_ENUMERATED,
    ELEM_TYPE_INTEGER,
)
from vermilion.core.card import Card, SimElem
from vermilion.core.constants import SIMULATED_CARD_NUM
from vermilion.core.products import by_demo

_log = logging.getLogger(__name__)

_RANGE_RE = re.compile(r"\s*(-?\d+)\s*-\s*(-?\d+)")
_DB_TLV_TYPES = (
    asound.TLVT_DB_SCALE,
    asound.TLVT_DB_LINEAR,
    asound.TLVT_DB_RANGE,
    asound.TLVT_DB_MINMAX,
    asound.TLVT_DB_MINMAX_MUTE,
)


class StateFileError(Exception):
    pass


def _first_compound(node: asound.ConfigNode, expected_id: str | None = None) -> asound.ConfigNode:
    """Descend into the first child, which must be a compound node."""
    if node.type != CONFIG_TYPE_COMPOUND:
        raise StateFileError(f"config node '{node.id}' is not of type compound")
    child = next(node.children(), None)
    if child is None:
        raise StateFileError(f"compound config node '{node.id}' has no children")
    if child.type != CONFIG_TYPE_COMPOUND:
        raise StateFileError(f"config node {node.id}->{child.id} is not of type compound")
    if expected_id and child.id != expected_id:
        raise StateFileError(f"found config node {node.id}->{child.id} instead of {expected_id}")
    return child


def _parse_int_array(node: asound.ConfigNode) -> list[int]:
    values: list[int] = []
    for child in node.children():
        t = child.type
        if t == CONFIG_TYPE_STRING:
            if child.string() == "true":
                values.append(1)
        elif t == CONFIG_TYPE_INTEGER:
            values.append(child.integer())
    return values


def _parse_comment(comment: asound.ConfigNode, elem: SimElem) -> None:
    tlv = None
    db_min = db_max = None
    for node in comment.children():
        key, t = node.id, node.type
        if key == "access" and t == CONFIG_TYPE_STRING:
            if "write" in node.string():
                elem.is_writable = True
        elif key == "type" and t == CONFIG_TYPE_STRING:
            elem.type = {
                "BOOLEAN": ELEM_TYPE_BOOLEAN,
                "ENUMERATED": ELEM_TYPE_ENUMERATED,
                "INTEGER": ELEM_TYPE_INTEGER,
            }.get(node.string(), elem.type)
        elif key == "count":
            elem.count = node.integer()
        elif key == "item":
            if node.is_array() >= 0:
                elem.item_names = [
                    c.string() for c in node.children() if c.type == CONFIG_TYPE_STRING
                ]
        elif key == "range" and t == CONFIG_TYPE_STRING:
            # "%d - %d", e.g. "0 - 172 (step 1)"
            m = _RANGE_RE.match(node.string())
            if m:
                elem.min_val, elem.max_val = int(m.group(1)), int(m.group(2))
        elif key == "tlv" and t == CONFIG_TYPE_STRING:
            # hex dump of the TLV, one 32 bit word per 8 digits
            hex_tlv = node.string()
            try:
                tlv = [int(hex_tlv[i : i + 8], 16) for i in range(0, len(hex_tlv), 8)]
            except ValueError:
                pass
        elif key == "dbmin" and t == CONFIG_TYPE_INTEGER:
            db_min = node.integer()
        elif key == "dbmax" and t == CONFIG_TYPE_INTEGER:
            db_max = node.integer()

    # dB information: the TLV if saved, otherwise the dB range
    try:
        if tlv and tlv[0] in _DB_TLV_TYPES:
            elem.db = asound.DbTlv(tlv, elem.min_val, elem.max_val)
        elif db_min is not None and db_max is not None:
            elem.db = asound.DbTlv.minmax(db_min, db_max, elem.min_val, elem.max_val)
    except asound.AlsaError as e:
        _log.debug(f"{e} for {elem.name or elem.numid}")


def _add_control(card: Card, node: asound.ConfigNode) -> None:
    try:
        numid = int(node.id or "")
    except TypeError, ValueError:
        numid = 0

    elem = SimElem(card, numid)
    iface = name = None
    seen_value = False
    value_type = None
    int_value = 0
    string_value = None
    int_values = None
    array_count = 0

    for child in node.children():
        key, t = child.id, child.type
        if key == "iface":
            if t != CONFIG_TYPE_STRING:
                return
            iface = child.string()
        elif key == "name":
            if t != CONFIG_TYPE_STRING:
                return
            name = child.string()
        elif key == "value":
            seen_value = True
            value_type = t
            if t == CONFIG_TYPE_INTEGER:
                int_value = child.integer()
            elif t == CONFIG_TYPE_STRING:
                string_value = child.string()
            elif t == CONFIG_TYPE_COMPOUND:
                array_count = child.is_array()
                if name == "Level Meter":
                    elem.count = array_count
                    value_type = CONFIG_TYPE_INTEGER
                    int_value = 0
                else:
                    int_values = _parse_int_array(child)
            else:
                _log.debug(f"skipping value type for {numid}; is {t}, not int or string")
                return
        elif key == "comment":
            _parse_comment(child, elem)
        elif key == "index":
            pass
        else:
            _log.debug(f"skipping unknown node {key} for {numid}")
            return

    # only interested in CARD, MIXER, and PCM
    if iface not in ("CARD", "MIXER", "PCM"):
        if iface is None:
            _log.debug(f"missing iface node in control id {numid}")
        return
    if not name:
        _log.debug(f"missing name node in control id {numid}")
        return
    if not seen_value:
        _log.debug(f"missing value node in control id {numid}")
        return

    if value_type == CONFIG_TYPE_INTEGER:
        elem.value = int_value
    elif value_type == CONFIG_TYPE_STRING:
        if elem.type == ELEM_TYPE_BOOLEAN:
            elem.value = 1 if string_value == "true" else 0
        elif elem.type == ELEM_TYPE_ENUMERATED:
            items = elem.item_names or []
            if string_value in items:
                elem.value = items.index(string_value)
        else:
            return

    elem.name = name

    if int_values is not None and name.startswith("Master"):
        # Gen 1 multi-channel control: split into per-channel elements
        n = min(array_count, elem.count)
        for i in range(n):
            e = SimElem(card, numid, name, elem.type, 1, i)
            for attr in ("min_val", "max_val", "db", "is_writable", "item_names"):
                setattr(e, attr, getattr(elem, attr))
            e.value = int_values[i] if i < len(int_values) else 0
            card.add_elem(e)
    elif int_values is not None:
        # multi-value element (e.g. biquad coefficients)
        elem.values = (int_values + [0] * elem.count)[: elem.count]
        card.add_elem(elem)
    else:
        card.add_elem(elem)


def load_card(path: Path) -> Card:
    """Parse a .state file into a new simulated Card (not initialised)."""
    try:
        top, free = asound.load_config_file(path)
    except asound.AlsaError as e:
        raise StateFileError(str(e)) from e

    try:
        node = _first_compound(top, "state")
        node = _first_compound(node)
        node = _first_compound(node, "control")

        card = Card(SIMULATED_CARD_NUM)
        card.name = path.stem
        card.serial = card.name
        # the product a demo file simulates, for its port names and digital I/O
        product = by_demo(card.name)
        if product:
            card.pid = product.pid

        for child in node.children():
            if child.type == CONFIG_TYPE_COMPOUND:
                _add_control(card, child)
    finally:
        free()

    return card

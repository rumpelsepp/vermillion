# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Behaviour of individual controls that goes beyond setting one value."""

from typing import TYPE_CHECKING

from vermilion.core.util import get_num_from_string, get_two_nums_from_string

if TYPE_CHECKING:
    from vermilion.core.card import Elem

# the direct monitor element and the mirrored mix elements per mode
type DirectMonitorMix = tuple[Elem, list[Elem]]


def direct_monitor_mix_elems(elem: Elem) -> DirectMonitorMix | None:
    """Mixer gains mirrored into "Monitor Mix" controls (4th Gen Solo/2i2).

    If direct monitor is enabled and a Mix A/B gain is changed, the
    corresponding Monitor Mix Playback Volume controls are changed too,
    so that the mix settings are restored when direct monitor is enabled
    again later. Returns (direct_monitor_elem, [mix elems per mode]) or
    None.
    """
    card = elem.card
    dm = card.elem_by_prefix("Direct Monitor Playback")
    if not dm:
        return None
    if not elem.name.startswith("Mix ") or "Playback Volume" not in elem.name:
        return None

    letter = elem.name[4]
    num = get_num_from_string(elem.name)

    # 4th Gen Solo
    if "Switch" in dm.name:
        e = card.elem(f"Monitor Mix {letter} Input {num:02d} Playback Volume")
        return (dm, [e]) if e else None

    # 4th Gen 2i2
    if "Enum" in dm.name:
        elems = []
        for i in (1, 2):
            e = card.elem(f"Monitor {i} Mix {letter} Input {num:02d} Playback Volume")
            if not e:
                return None
            elems.append(e)
        return dm, elems

    return None


def set_gain(elem: Elem, value: int, dm_info: DirectMonitorMix | None = None) -> None:
    """Set a gain value, mirroring into the direct monitor mix if needed."""
    elem.set_value(value)
    if not dm_info:
        return
    dm, mix_elems = dm_info
    mode = dm.get_value()
    if not mode or mode - 1 >= len(mix_elems):
        return
    mix_elems[mode - 1].set_value(value)


def input_select_matches(item_name: str, line_num: int) -> bool:
    """Does an "Input Select" enum item select this input (or range)?"""
    a, b = get_two_nums_from_string(item_name)
    if b == -1:
        return a == line_num
    return a <= line_num <= b


def select_input(elem: Elem, line_num: int) -> None:
    for i, name in enumerate(elem.items()):
        if input_select_matches(name, line_num):
            elem.set_value(i)
            return

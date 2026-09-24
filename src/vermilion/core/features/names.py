# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Port names: generic, device-specific and user-defined (custom) names.

Custom names are stored in simulated BYTES elements (e.g.
"Analogue In 1 Name") which are persisted in the state file. If a
future driver provides real elements with these names they are used
directly.
"""

from typing import TYPE_CHECKING

from vermilion.core.asound import ELEM_TYPE_BYTES
from vermilion.core.constants import PC

if TYPE_CHECKING:
    from vermilion.core.card import Card
    from vermilion.core.ports import Port

MAX_CUSTOM_NAME_LEN = 32
MAX_PAIR_NAME_LEN = 32


class PortNames:
    """The name controls: the device name ("Name") and a custom name for
    every routing source and sink (DSP inputs just show numbers)."""

    def __init__(self, card: Card) -> None:
        self.card = card
        if not card.serial:
            return
        card.optional_elem("Name", ELEM_TYPE_BYTES, size=MAX_CUSTOM_NAME_LEN)
        if not card.routing_srcs:
            return

        for port in card.ports:
            if not port.is_src and port.port_category == PC.DSP:
                continue
            elem_name = port.control_name("Name")
            if not elem_name:
                continue
            port.custom_name_elem = card.optional_elem(
                elem_name, ELEM_TYPE_BYTES, size=MAX_CUSTOM_NAME_LEN
            )
            port.custom_name_elem.connect("changed", lambda _e, port=port: self._renamed(port))

        for port in card.ports:
            port.update_display_name()

    @staticmethod
    def _renamed(port: Port) -> None:
        port.update_display_name()
        port.emit("name-changed")

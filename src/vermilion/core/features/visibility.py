# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Show/hide ("enable") state of routing sources and sinks.

Each port gets a simulated boolean element (e.g. "Analogue In 1
Switch"), persisted in the state file and defaulting to enabled.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from vermilion.core.asound import ELEM_TYPE_BOOLEAN
from vermilion.core.constants import PC, UiUpdate

if TYPE_CHECKING:
    from vermilion.core.card import Card
    from vermilion.core.ports import Port


class PortVisibility:
    """Whether each routing source and sink is shown (by an element such
    as "Analogue In 1 Switch", persisted in the state file and defaulting
    to shown)."""

    def __init__(self, card: Card) -> None:
        self.card = card
        if not card.serial or not card.routing_srcs:
            return
        for port in card.ports:
            name = port.control_name("Switch")
            if not name:
                continue
            is_new = card.elem(name) is None
            port.enable_elem = card.optional_elem(name, ELEM_TYPE_BOOLEAN, default=1)
            if is_new:
                port.enable_elem.connect("changed", lambda _e, port=port: self._changed(port))

    def _changed(self, port: Port) -> None:
        card = self.card
        pc = port.port_category
        card.emit("port-visibility-changed", pc, port.is_src)
        flags = UiUpdate(0)
        if pc == PC.MIX:
            flags |= UiUpdate.MIXER_GRID
        if port.is_src or pc == PC.HW:
            flags |= UiUpdate.MONITOR_GROUPS
        if flags:
            card.schedule_ui_update(flags)

    @staticmethod
    def all_hidden(ports: Sequence[Port], port_category: int) -> bool:
        """Are all ports of a category hidden?"""
        return not any(p.port_category == port_category and p.enabled for p in ports)

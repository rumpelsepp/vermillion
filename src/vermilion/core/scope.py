# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lifetime of signal connections.

The model emits GObject signals; a GUI part connects to them through a
Scope, which disconnects everything at once when the widgets it
belongs to go away.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from gi.repository import GLib, GObject

if TYPE_CHECKING:
    from vermilion.core.card import Elem


class Scope:
    """Collects signal handlers (and cleanup functions) for later removal."""

    def __init__(self) -> None:
        self._handlers: list[tuple[GObject.Object, int]] = []
        self._cleanups: list[Callable[[], object]] = []

    def connect(self, obj: GObject.Object, signal: str, callback: Callable[..., Any]) -> None:
        self._handlers.append((obj, obj.connect(signal, callback)))

    def watch(self, elem: Elem, fn: Callable[[Elem], object]) -> None:
        """Call fn(elem) when elem changes."""
        self.connect(elem, "changed", fn)

    def timer(self, seconds: int, fn: Callable[[], object]) -> None:
        """Call fn() every `seconds` seconds."""

        def tick() -> bool:
            fn()
            return GLib.SOURCE_CONTINUE

        source = GLib.timeout_add_seconds(seconds, tick)
        self.on_close(lambda: GLib.source_remove(source))

    def on_close(self, fn: Callable[[], object]) -> None:
        self._cleanups.append(fn)

    def close(self) -> None:
        for obj, handler_id in self._handlers:
            obj.disconnect(handler_id)
        self._handlers = []
        for fn in self._cleanups:
            fn()
        self._cleanups = []

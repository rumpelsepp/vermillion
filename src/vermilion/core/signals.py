# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Declaring GObject signals (``__gsignals__``)."""

from gi.repository import GObject

type SignalSpec = tuple[GObject.SignalFlags, None, tuple[type, ...]]


def signal(*args: type) -> SignalSpec:
    """A signal without return value, with arguments of the given types."""
    return (GObject.SignalFlags.RUN_FIRST, None, args)

# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later
__version__ = "0.1.0"

# imported for its side effect: it sends the log messages of GLib to
# stderr, which has to happen before GLib starts a thread
from vermilion import log as _log  # noqa: F401

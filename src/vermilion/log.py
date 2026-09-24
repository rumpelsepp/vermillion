# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Logging the GNOME way: Python logging, written by GLib.

Modules log with logging.getLogger(__name__); setup() hands the records
to GLib's structured logging (log domain "vermilion"). GLib writes them
to the journal when the application runs from the desktop and to stderr
otherwise (all levels, stdout is left to the command line tool), and follows its environment variables: debug and info
messages only appear with G_MESSAGES_DEBUG=vermilion (or all), and
G_DEBUG=fatal-warnings makes warnings fatal.
"""

import logging
import traceback

from gi.repository import GLib

DOMAIN = "vermilion"

# all messages to stderr (GLib writes debug and info ones to stdout, the
# output of the command line tool); only possible before GLib has
# started a thread, so on import (see vermilion/__init__.py)
GLib.log_writer_default_set_use_stderr(True)

_LEVELS = (
    (logging.ERROR, GLib.LogLevelFlags.LEVEL_CRITICAL),
    (logging.WARNING, GLib.LogLevelFlags.LEVEL_WARNING),
    (logging.INFO, GLib.LogLevelFlags.LEVEL_INFO),
)


def _glib_level(levelno: int) -> GLib.LogLevelFlags:
    # GLib's own ERROR level aborts: errors are critical messages
    for python, glib in _LEVELS:
        if levelno >= python:
            return glib
    return GLib.LogLevelFlags.LEVEL_DEBUG


class GLibHandler(logging.Handler):
    """Writes log records with GLib (structured, with the code location)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            module = record.name.removeprefix(f"{DOMAIN}.")
            message = f"{module}: {record.getMessage()}"
            if record.exc_info:
                message += "\n" + "".join(traceback.format_exception(*record.exc_info))
            fields = {
                "MESSAGE": message,
                "CODE_FILE": record.pathname,
                "CODE_LINE": str(record.lineno),
                "CODE_FUNC": record.funcName,
            }
            GLib.log_variant(
                DOMAIN,
                _glib_level(record.levelno),
                GLib.Variant("a{sv}", {k: GLib.Variant("s", v) for k, v in fields.items()}),
            )
        # any error, as logging.Handler.emit is meant to: handleError() reports
        # it without raising in the code that logged
        except Exception:  # noqa: BLE001
            self.handleError(record)


def setup() -> None:
    """Send the records of the application's loggers to GLib. Debug
    records are only created when GLib would show them."""
    logger = logging.getLogger(DOMAIN)
    if any(isinstance(h, GLibHandler) for h in logger.handlers):
        return
    logger.addHandler(GLibHandler())
    logger.propagate = False
    debug = not GLib.log_writer_default_would_drop(GLib.LogLevelFlags.LEVEL_DEBUG, DOMAIN)
    logger.setLevel(logging.DEBUG if debug else logging.WARNING)

# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Log records are written by GLib, and follow G_MESSAGES_DEBUG."""

import os
import subprocess
import sys

import pytest

SCRIPT = """
import logging
from vermilion import log
log.setup()
logger = logging.getLogger("vermilion.test")
logger.debug("a debug message")
logger.warning("a warning")
"""


def run(env: dict[str, str]) -> str:
    environ = {k: v for k, v in os.environ.items() if k != "G_MESSAGES_DEBUG"}
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        env=environ | env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stderr


def test_warnings_only_by_default() -> None:
    out = run({})
    assert "vermilion-WARNING" in out and "test: a warning" in out
    assert "debug message" not in out


@pytest.mark.parametrize("domains", ["vermilion", "all"])
def test_debug_with_g_messages_debug(domains: str) -> None:
    out = run({"G_MESSAGES_DEBUG": domains})
    assert "vermilion-DEBUG" in out and "test: a debug message" in out

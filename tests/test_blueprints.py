# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The .ui files are those compiled from the current Blueprint files."""

import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).parents[1].joinpath("tools", "blueprints.py")


def test_ui_files_are_up_to_date() -> None:
    result = subprocess.run(
        [sys.executable, TOOL, "--check"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr

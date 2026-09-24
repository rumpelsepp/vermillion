# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

from vermilion.core.storage import paths


@pytest.fixture(autouse=True)
def xdg_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the state, preferences and presets of a test in tmp_path."""
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path.joinpath("state"))
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path.joinpath("config"))
    monkeypatch.setattr(paths, "presets_dir", lambda: tmp_path.joinpath("presets"))
    return tmp_path

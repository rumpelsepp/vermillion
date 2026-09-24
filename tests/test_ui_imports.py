# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""All modules of the UI can be imported (e.g. no widget class derives
from a final GTK type, which only fails when its module is loaded)."""

import importlib
import pkgutil

import pytest

import vermilion.ui


@pytest.mark.parametrize(
    "name",
    [m.name for m in pkgutil.walk_packages(vermilion.ui.__path__, "vermilion.ui.")],
)
def test_import(name: str) -> None:
    importlib.import_module(name)

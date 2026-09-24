# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Access to UI resources: the GtkBuilder XML of the Blueprint files and
the style sheet.

The Blueprint (.blp) files are compiled to GtkBuilder XML (.ui) with
tools/blueprints.py (`just blueprints`); the package contains the .ui
files.
"""

from importlib import resources

from gi.repository import Gtk

_PKG = resources.files("vermilion")
_BLUEPRINTS = _PKG.joinpath("ui", "blueprints")
_DATA = _PKG.joinpath("data")


def blueprint(name: str) -> bytes:
    """The GtkBuilder XML compiled from ui/blueprints/<name>.blp."""
    try:
        return _BLUEPRINTS.joinpath(f"{name}.ui").read_bytes()
    except FileNotFoundError as e:
        # a source tree without the compiled files
        raise RuntimeError(f"{name}.ui is missing: run `just blueprints`") from e


def builder(name: str) -> Gtk.Builder:
    b = Gtk.Builder()
    b.add_from_string(blueprint(name).decode())
    return b


def data_path(name: str) -> str:
    return str(_DATA.joinpath(name))

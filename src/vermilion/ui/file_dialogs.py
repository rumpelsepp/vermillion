# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""File dialogs: load/save configuration, ALSA state files, interface
simulation."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

from gi.repository import Adw, Gio, GLib, Gtk

from vermilion.core.sim import StateFileError
from vermilion.ui.dialogs import show_error
from vermilion.ui.resources import blueprint

if TYPE_CHECKING:
    from vermilion.core.card import Card
    from vermilion.ui.app import Application

CONF = ("Vermilion configuration (.conf)", "*.conf")
STATE = ("ALSA state file (.state)", "*.state")


def pick_file(
    parent: Gtk.Widget | None,
    title: str,
    file_type: tuple[str, str],
    save: bool,
    use: Callable[[Path], str | None],
) -> None:
    """Let the user pick a file to open or save and pass its path to use,
    which returns an error message or None."""
    name, pattern = file_type
    file_filter = Gtk.FileFilter(name=name)
    file_filter.add_pattern(pattern)
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(file_filter)
    dialog = Gtk.FileDialog(title=title, filters=filters)
    window = parent.get_root() if parent else None
    window = window if isinstance(window, Gtk.Window) else None

    def done(d: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = d.save_finish(result) if save else d.open_finish(result)
        except GLib.Error as e:
            if not e.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                show_error(parent, e.message)
            return
        path = file.get_path() if file else None
        error = use(Path(path)) if path else None
        if error:
            show_error(parent, error)

    if save:
        dialog.save(window, None, done)
    else:
        dialog.open(window, None, done)


def simulate(parent: Gtk.Widget | None) -> None:
    def use(path: Path) -> str | None:
        # the type only: the application module imports this one
        app = cast("Application", Gio.Application.get_default())
        try:
            app.manager.add_simulated(path)
        except StateFileError as e:
            return str(e)
        return None

    pick_file(parent, "Simulate an Interface", STATE, False, use)


@Gtk.Template(string=blueprint("alsa_state_dialog"))
class AlsaStateDialog(Adw.Dialog):
    """Saving and restoring the controls of an interface with alsactl,
    and simulating an interface from a state file."""

    __gtype_name__ = "AlsaStateDialog"

    store_row: Adw.ActionRow = Gtk.Template.Child()
    restore_row: Adw.ActionRow = Gtk.Template.Child()

    def __init__(self, card: Card | None) -> None:
        super().__init__()
        self.card = card
        # alsactl needs a real interface
        real = bool(card and card.device)
        self.store_row.set_sensitive(real)
        self.restore_row.set_sensitive(real)

    def _alsactl(self, cmd: str, path: Path) -> str | None:
        assert self.card
        return self.card.config.alsactl(cmd, path)

    @Gtk.Template.Callback()
    def _on_store(self, _button: Gtk.Button) -> None:
        pick_file(self, "Save Controls", STATE, True, lambda path: self._alsactl("store", path))

    @Gtk.Template.Callback()
    def _on_restore(self, _button: Gtk.Button) -> None:
        pick_file(
            self, "Restore Controls", STATE, False, lambda path: self._alsactl("restore", path)
        )

    @Gtk.Template.Callback()
    def _on_simulate(self, _button: Gtk.Button) -> None:
        # the file dialog belongs to the window, this dialog closes
        window = self.get_root()
        self.close()
        simulate(window if isinstance(window, Gtk.Window) else None)

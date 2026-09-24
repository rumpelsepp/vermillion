# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The GTK application."""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from vermilion import log
from vermilion.core.manager import CardManager
from vermilion.core.sim import StateFileError
from vermilion.core.storage import state
from vermilion.ui.card_window import CardUI, NoCardWindow
from vermilion.ui.dialogs import HardwareDialog
from vermilion.ui.resources import data_path

if TYPE_CHECKING:
    from vermilion.core.card import Card

APP_ID = "org.rumpelsepp.vermilion"
APP_ICON = "audio-card"

ACCELS = {
    "win.load": ["<Control>o"],
    "win.save": ["<Control>s"],
    "window.close": ["<Control>w"],
    "win.detach": ["<Control><Shift>n"],
    "app.quit": ["<Control>q"],
    "win.page::routing": ["<Control>r"],
    "win.page::mixer": ["<Control>m"],
    "win.page::levels": ["<Control>l"],
    "win.page::dsp": ["<Control>d"],
    "win.page::settings": ["<Control>comma"],
    "win.page::controls": ["<Control>k"],
    "app.hardware": ["<Control>h"],
    "win.about": ["<Control>slash"],
    "win.device-info": ["<Control>i"],
}


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.manager = CardManager()
        self.card_uis: dict[Card, CardUI] = {}
        self.no_card_window: NoCardWindow | None = None
        # windows of cards which are restarting, by serial
        self.suspended: dict[str, CardUI] = {}
        self._started = False

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        GLib.set_application_name("Vermilion")
        display = Gdk.Display.get_default()
        assert display is not None
        # a device icon of the icon theme (the icon of the original was
        # not taken over)
        Gtk.Window.set_default_icon_name(APP_ICON)

        css = Gtk.CssProvider()
        css.load_from_path(data_path("style.css"))
        Gtk.StyleContext.add_provider_for_display(
            display,
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        for action, accels in ACCELS.items():
            self.set_accels_for_action(action, accels)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)

        hardware = Gio.SimpleAction.new("hardware", None)
        hardware.connect(
            "activate",
            lambda *_: HardwareDialog().present(self.get_active_window()),
        )
        self.add_action(hardware)

        self.manager.connect("card-added", lambda _m, c: self._on_card_added(c))
        self.manager.connect("card-removed", lambda _m, c: self._on_card_removed(c))

    # Windows are only created in activate and open: GTK takes the
    # activation token of the launch (which lets the first window take
    # the focus) just before these. A window presented in startup leaves
    # the token unused; a later window would present it expired, and GNOME
    # would say "... is ready" instead of showing the window.

    def _start(self) -> bool:
        """Look for interfaces (once); False if already done."""
        if self._started:
            return False
        self._started = True
        self.manager.start()
        return True

    def do_activate(self) -> None:
        if self._start():
            self._update_no_card_window()
            return
        # launched again: show the window
        window = self.get_active_window()
        if window:
            window.present()

    def do_open(self, files: Sequence[Gio.File], n_files: int, hint: str) -> None:
        self._start()
        for f in files:
            path = f.get_path()
            if not path:
                continue
            try:
                self.manager.add_simulated(Path(path))
            except StateFileError as e:
                print(f"Error opening {path}: {e}", file=sys.stderr)
        self._update_no_card_window()

    def do_shutdown(self) -> None:
        for card in self.manager.cards:
            if card.device_state:
                card.device_state.flush()
        state.flush_now()
        Adw.Application.do_shutdown(self)

    # card windows

    def _on_card_added(self, card: Card) -> None:
        old = self.card_uis.pop(card, None)
        if old:
            old.destroy()
        self.card_uis[card] = CardUI(self, card)
        # the restarted card replaces the waiting window
        old = self.suspended.pop(card.serial, None) if card.serial else None
        if old:
            old.destroy()
        self._update_no_card_window()

    def _on_card_removed(self, card: Card) -> None:
        ui = self.card_uis.pop(card, None)
        if ui:
            if card.serial and self.manager.is_reopen_pending(card.serial):
                ui.suspend()
                self.suspended[card.serial] = ui
            else:
                ui.destroy()
        self._update_no_card_window()

    def card_ui_closed(self, card_ui: CardUI) -> None:
        if self.card_uis.get(card_ui.card) is card_ui:
            del self.card_uis[card_ui.card]
        serial = card_ui.card.serial
        if serial and self.suspended.get(serial) is card_ui:
            del self.suspended[serial]
        # closing the window of an interface is not "no interface found";
        # the application quits when its last window is closed

    def _update_no_card_window(self) -> None:
        """Show the "no interface" window while no interface is present."""
        if self.manager.cards or self.suspended:
            if self.no_card_window:
                self.no_card_window.destroy()
                self.no_card_window = None
            return
        if not self.no_card_window:
            window = NoCardWindow(self)
            window.connect("destroy", self._no_card_destroyed)
            self.no_card_window = window
        self.no_card_window.present()

    def _no_card_destroyed(self, window: Gtk.Widget) -> None:
        if self.no_card_window is window:
            self.no_card_window = None


def main() -> int:
    log.setup()
    app = Application()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

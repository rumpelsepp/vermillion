# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Presets button on the controls page."""

from typing import TYPE_CHECKING

from gi.repository import Gio, GLib, Gtk

from vermilion.ui.dialogs import SavePresetDialog, show_error

if TYPE_CHECKING:
    from vermilion.core.card import Card
    from vermilion.ui.card_window import CardUI


class PresetsButton(Gtk.MenuButton):
    """Menu to load, delete and save presets; the menu is built from the
    saved presets each time it is opened."""

    def __init__(self, card_ui: CardUI) -> None:
        super().__init__(label="Presets")
        self.card_ui = card_ui

        group = Gio.SimpleActionGroup()
        for name, param, fn in (
            ("load", "s", self._on_load),
            ("delete", "s", self._on_delete),
            ("save", None, self._on_save),
        ):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new(param) if param else None)
            action.connect("activate", fn)
            group.add_action(action)
        self.insert_action_group("presets", group)

        self.set_create_popup_func(self._build_menu)

    @property
    def card(self) -> Card:
        return self.card_ui.card

    def _build_menu(self, _button: Gtk.MenuButton) -> None:
        menu = Gio.Menu()
        names = self.card.presets.names()
        if names:
            load = Gio.Menu()
            delete = Gio.Menu()
            for name in names:
                for section, action in ((load, "presets.load"), (delete, "presets.delete")):
                    item = Gio.MenuItem.new(name, None)
                    item.set_action_and_target_value(action, GLib.Variant("s", name))
                    section.append_item(item)
            menu.append_section(None, load)
            menu.append_submenu("Delete Preset", delete)
        menu.append("Save as Preset…", "presets.save")
        self.set_menu_model(menu)

    def _on_load(self, _action: Gio.SimpleAction, param: GLib.Variant) -> None:
        error = self.card.presets.load(param.get_string())
        if error:
            show_error(self.card_ui.window, error)

    def _on_delete(self, _action: Gio.SimpleAction, param: GLib.Variant) -> None:
        self.card.presets.delete(param.get_string())

    def _on_save(self, _action: Gio.SimpleAction, _param: GLib.Variant | None) -> None:
        SavePresetDialog(self.card, self.card_ui.window)

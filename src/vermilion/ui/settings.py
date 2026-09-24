# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The settings page: all settings of an interface in sections."""

from typing import TYPE_CHECKING

from gi.repository import Adw, GObject, Gtk

from vermilion.core.features.levels import LEVELS_RATES
from vermilion.ui.configuration import ConfigurationSections
from vermilion.ui.panels import StartupSections
from vermilion.ui.resources import blueprint

if TYPE_CHECKING:
    from vermilion.core.scope import Scope
    from vermilion.ui.card_window import CardUI


@Gtk.Template(string=blueprint("settings_page"))
class SettingsPage(Adw.PreferencesPage):
    __gtype_name__ = "SettingsPage"

    device_group: Adw.PreferencesGroup = Gtk.Template.Child()
    front_panel_group: Adw.PreferencesGroup = Gtk.Template.Child()
    autogain_group: Adw.PreferencesGroup = Gtk.Template.Child()
    io_group: Adw.PreferencesGroup = Gtk.Template.Child()
    monitor_group: Adw.PreferencesGroup = Gtk.Template.Child()
    startup_group: Adw.PreferencesGroup = Gtk.Template.Child()
    actions_group: Adw.PreferencesGroup = Gtk.Template.Child()
    display_group: Adw.PreferencesGroup = Gtk.Template.Child()
    restore_row: Adw.SwitchRow = Gtk.Template.Child()
    solo_mutes_row: Adw.SwitchRow = Gtk.Template.Child()
    solo_dim_row: Adw.SpinRow = Gtk.Template.Child()
    labels_row: Adw.SwitchRow = Gtk.Template.Child()
    rate_row: Adw.ComboRow = Gtk.Template.Child()

    def __init__(
        self,
        card_ui: CardUI,
        scope: Scope,
        configuration: bool = True,
        startup: bool = True,
        display: bool = True,
    ) -> None:
        """configuration: device, I/O, monitor group sections (interfaces
        with a mixer); startup: startup settings and device actions;
        display: preferences of this program."""
        super().__init__()
        self.card_ui = card_ui
        self.config = None
        if configuration:
            self.config = ConfigurationSections(card_ui, self)
        if startup:
            StartupSections(card_ui, scope, self)
        if display:
            self._display_section()

    def _display_section(self) -> None:
        card = self.card_ui.card
        self.display_group.set_visible(True)

        if card.device_state:
            self.restore_row.set_visible(True)
            self.restore_row.set_active(card.prefs.restore_device_state)
            self.restore_row.connect("notify::active", self._on_restore)

        if card.mixer_mute:
            self.solo_mutes_row.set_visible(True)
            self.solo_dim_row.set_visible(True)
            self.solo_mutes_row.set_active(card.prefs.solo_mutes)
            self.solo_dim_row.set_value(card.prefs.solo_dim_db)
            self.solo_dim_row.set_sensitive(not card.prefs.solo_mutes)
            self.solo_mutes_row.connect("notify::active", self._on_solo_mutes)
            self.solo_dim_row.connect("notify::value", self._on_solo_dim)

        self.labels_row.set_active(card.prefs.show_bottom_right_labels)
        self.labels_row.connect("notify::active", self._on_labels)

        self.rate_row.set_visible(card.has_levels)
        self.rate_row.set_model(Gtk.StringList.new([label for label, _, _ in LEVELS_RATES]))
        self.rate_row.set_selected(card.prefs.levels_rate_index)
        self.rate_row.connect("notify::selected", self._on_rate)

    def _on_solo_mutes(self, row: Adw.SwitchRow, _pspec: GObject.ParamSpec | None) -> None:
        card = self.card_ui.card
        card.prefs.solo_mutes = row.get_active()
        self.solo_dim_row.set_sensitive(not row.get_active())
        if card.mixer_mute:
            card.mixer_mute.apply()

    def _on_solo_dim(self, row: Adw.SpinRow, _pspec: GObject.ParamSpec | None) -> None:
        card = self.card_ui.card
        card.prefs.solo_dim_db = round(row.get_value())
        if card.mixer_mute:
            card.mixer_mute.apply()

    def _on_restore(self, row: Adw.SwitchRow, _pspec: GObject.ParamSpec | None) -> None:
        self.card_ui.card.prefs.restore_device_state = row.get_active()

    def _on_labels(self, row: Adw.SwitchRow, _pspec: GObject.ParamSpec | None) -> None:
        self.card_ui.card.prefs.show_bottom_right_labels = row.get_active()
        self.card_ui.rebuild_mixer_grid()

    def _on_rate(self, row: Adw.ComboRow, _pspec: GObject.ParamSpec | None) -> None:
        card = self.card_ui.card
        card.prefs.levels_rate_index = row.get_selected()
        if card.levels:
            card.levels.start()

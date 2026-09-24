# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Simple pages (FCP, firmware update, unknown) and the startup sections."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk

from vermilion.core.device.maintenance import Maintenance, MaintenanceError
from vermilion.ui.dialogs import show_error
from vermilion.ui.resources import blueprint
from vermilion.ui.widgets.elem import ElemComboRow, elem_switch_row

if TYPE_CHECKING:
    from vermilion.core.scope import Scope
    from vermilion.ui.card_window import CardUI
    from vermilion.ui.settings import SettingsPage


@Gtk.Template(string=blueprint("fcp_panel"))
class FcpPanel(Adw.Bin):
    """The interface has the FCP driver, which is not supported yet."""

    __gtype_name__ = "FcpPanel"

    self_scrolling = True


@Gtk.Template(string=blueprint("firmware_required_panel"))
class FirmwareRequiredPanel(Adw.Bin):
    """The firmware is older than the driver requires."""

    __gtype_name__ = "FirmwareRequiredPanel"

    self_scrolling = True


@Gtk.Template(string=blueprint("unknown_panel"))
class UnknownPanel(Adw.Bin):
    __gtype_name__ = "UnknownPanel"

    self_scrolling = True


class StartupSections:
    """Startup settings (stored in the device's flash) and device actions
    (reboot, reset) on the settings page."""

    def __init__(self, card_ui: CardUI, scope: Scope, page: SettingsPage) -> None:
        self.card_ui = card_ui
        self.scope = scope
        self.settings = page.startup_group
        self.actions = page.actions_group

        self._add_bool(
            "Standalone Switch",
            "Standalone",
            "When Standalone mode is enabled, the interface will continue to "
            "route audio as per the previous routing and mixer settings "
            "after it has been disconnected from a computer. By configuring "
            "the routing between the hardware and mixer inputs and outputs "
            "appropriately, the interface can act as a standalone preamp or "
            "mixer.",
        )
        self._add_bool(
            "Phantom Power Persistence Capture Switch",
            "Phantom Power Persistence",
            "When Phantom Power Persistence is enabled, the interface will "
            "restore the previous Phantom Power/48V setting when the "
            "interface is turned on. For the safety of microphones which can "
            "be damaged by phantom power, the interface defaults to having "
            "phantom power disabled when it is turned on.",
        )
        has_msd = self._add_bool(
            "MSD Mode Switch",
            "MSD (Mass Storage Device) Mode",
            "When MSD Mode is enabled (as it is from the factory), the "
            "interface has reduced functionality. You’ll want to have this "
            "disabled. On the other hand, when MSD Mode is enabled, the "
            "interface presents itself as a Mass Storage Device (like a USB "
            "stick), containing a link to the Focusrite web site encouraging "
            "you to register your product and download the proprietary "
            "drivers which can’t be used on Linux.",
        )
        has_spdif_mode = self._add_spdif_mode()
        self._add_reset_actions(has_msd or has_spdif_mode)

        self.settings.set_visible(bool(self._settings))
        self.actions.set_visible(bool(self._actions))

    _settings = 0
    _actions = 0

    def _add_bool(self, elem_name: str, heading: str, description: str) -> bool:
        elem = self.card_ui.card.elem(elem_name)
        if not elem:
            return False
        self.settings.add(elem_switch_row(self.scope, elem, heading, description))
        self._settings += 1
        return True

    def _add_spdif_mode(self) -> bool:
        # a mode that needs a reboot (the others are in the configuration)
        card = self.card_ui.card
        product = card.product
        if not product or not product.digital_io_control or product.digital_io_live:
            return False
        elem = card.elem_by_prefix(product.digital_io_control)
        if not elem:
            return False
        title = product.digital_io_control
        self.settings.add(ElemComboRow(self.scope, elem, title, product.digital_io_help))
        self._settings += 1
        return True

    def _add_action(
        self,
        heading: str,
        button_label: str,
        description: str,
        callback: Callable[[], object],
        style: str | None = None,
    ) -> None:
        row = Adw.ActionRow(title=heading, subtitle=description)
        button = Gtk.Button(label=button_label, valign=Gtk.Align.CENTER)
        if style:
            button.add_css_class(style)
        button.connect("clicked", lambda _b: callback())
        row.add_suffix(button)
        self.actions.add(row)
        self._actions += 1

    def _reboot(self, maintenance: Maintenance) -> None:
        try:
            maintenance.reboot()
        except MaintenanceError as e:
            show_error(self.card_ui.window, str(e))

    def _add_reset_actions(self, show_reboot: bool) -> None:
        card_ui = self.card_ui
        maintenance = Maintenance.of(card_ui.card)
        if not maintenance:
            return

        if show_reboot:
            self._add_action(
                "Reboot Device",
                "Reboot",
                "Rebooting the interface will apply changes made to the "
                "startup configuration. This will take a few seconds.",
                lambda: self._reboot(maintenance),
            )

        self._add_action(
            "Reset Configuration",
            "Reset",
            "Resetting the configuration will reset the interface to its "
            "factory default settings. The firmware will be left unchanged.",
            lambda: card_ui.confirm_reset_config(maintenance),
            "destructive-action",
        )

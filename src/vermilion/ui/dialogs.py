# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stand-alone windows and dialogs."""

from collections.abc import Callable
from typing import TYPE_CHECKING

import gi
from gi.repository import Adw, GLib, Gtk

from vermilion import __version__
from vermilion.core.device.info import DeviceInfo, Row
from vermilion.core.device.maintenance import Reporter
from vermilion.core.products import PRODUCTS
from vermilion.core.storage import presets
from vermilion.ui.resources import blueprint, builder

if TYPE_CHECKING:
    from vermilion.core.card import Card
    from vermilion.ui.card_window import CardUI


def show_error(parent: Gtk.Widget | None, message: str) -> None:
    if parent is None:
        print(message)
        return
    dialog = Adw.AlertDialog(heading="Error", body=message)
    dialog.add_response("close", "_Close")
    dialog.present(parent)


def confirm(
    parent: Gtk.Widget | None,
    heading: str,
    body: str,
    action_label: str,
    callback: Callable[[], object],
    destructive: bool = True,
) -> None:
    """Ask for confirmation, then call callback()."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "_Cancel")
    dialog.add_response("ok", action_label)
    dialog.set_response_appearance(
        "ok",
        Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED,
    )
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
        if response == "ok":
            callback()

    dialog.connect("response", on_response)
    dialog.present(parent)


def show_about(parent: Gtk.Widget | None) -> None:
    about = builder("about_dialog").get_object("about")
    assert isinstance(about, Adw.AboutDialog)
    about.set_version(__version__)
    about.present(parent)


@Gtk.Template(string=blueprint("hardware_dialog"))
class HardwareDialog(Adw.Dialog):
    __gtype_name__ = "HardwareDialog"

    page: Adw.PreferencesPage = Gtk.Template.Child()

    def __init__(self) -> None:
        super().__init__()
        groups: dict[str, Adw.PreferencesGroup] = {}
        for product in PRODUCTS:
            if product.family not in groups:
                groups[product.family] = Adw.PreferencesGroup(title=product.family)
                self.page.add(groups[product.family])
            groups[product.family].add(Adw.ActionRow(title=product.name))


def _versions() -> list[Row]:
    """Versions of the GUI libraries (for the "System" section)."""
    return [
        Row(
            "GTK",
            f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}",
        ),
        Row(
            "libadwaita",
            f"{Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}",
        ),
        Row("PyGObject", ".".join(map(str, gi.version_info))),
    ]


@Gtk.Template(string=blueprint("device_info_dialog"))
class DeviceInfoDialog(Adw.Dialog):
    """Everything known about the interface of a window, or, in the window
    shown when no interface is found, about the Focusrite USB devices."""

    __gtype_name__ = "DeviceInfoDialog"

    toasts: Adw.ToastOverlay = Gtk.Template.Child()
    page: Adw.PreferencesPage = Gtk.Template.Child()

    def __init__(self, card: Card | None) -> None:
        super().__init__()
        if card:
            self.set_title(f"{card.name} Information")
        else:
            self.page.set_description(
                "No interface is open. The Focusrite devices on the USB bus are listed "
                "below; a supported one without an ALSA sound card is usually missing "
                "its driver or in MSD mode."
            )
        self.info = DeviceInfo(card, _versions())

        for section in self.info.sections:
            group = Adw.PreferencesGroup(title=section.title)
            for row in section.rows:
                # the label on the left, the value on the right, as in the
                # system details of GNOME Settings
                action_row = Adw.ActionRow(title=row.label)
                value = Gtk.Label(
                    label=row.value,
                    selectable=True,
                    wrap=True,
                    xalign=1.0,
                    justify=Gtk.Justification.RIGHT,
                    # the free width of the row, wrapped only when longer
                    hexpand=True,
                    width_chars=min(len(row.value), 24),
                    max_width_chars=40,
                    css_classes=["dim-label"],
                )
                action_row.add_suffix(value)
                group.add(action_row)
            self.page.add(group)

    @Gtk.Template.Callback()
    def _on_copy(self, _button: Gtk.Button) -> None:
        self.get_clipboard().set(self.info.as_text())
        self.toasts.add_toast(Adw.Toast(title="Copied to the clipboard"))


@Gtk.Template(string=blueprint("progress_dialog"))
class ProgressDialog(Adw.Dialog):
    """Progress of a long-running device operation.

    start(reporter) starts it in a worker thread (see
    core.device.maintenance).
    """

    __gtype_name__ = "ProgressDialog"

    message: Gtk.Label = Gtk.Template.Child()
    stack: Gtk.Stack = Gtk.Template.Child()
    progress: Gtk.ProgressBar = Gtk.Template.Child()

    def __init__(
        self,
        card_ui: CardUI,
        title: str,
        message: str,
        start: Callable[[Reporter], object],
    ) -> None:
        super().__init__(title=title)
        self.card_ui = card_ui
        self.card = card_ui.card
        self.serial = card_ui.card.serial
        self._timer = 0
        self._reboot_ticks = 0
        self.message.set_text(message)
        self.connect("closed", lambda _d: self._cleanup())

        # if the card goes away while rebooting, the window stays open
        # until the card is back (see CardUI.suspend)
        self.present(card_ui.window)
        start(Reporter(self._on_progress, self._on_reboot))

    def _cleanup(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self.card_ui.app.manager.unregister_reopen(self.serial)
        if self.card_ui.modal is self:
            self.card_ui.modal = None

    def _finish(self, text: str | None = None) -> None:
        if text:
            self.message.set_text(text)
        self.stack.set_visible_child_name("done")
        self.set_can_close(True)

    @Gtk.Template.Callback()
    def on_close(self, _button: Gtk.Button) -> None:
        self.close()

    def _on_progress(self, text: str | None, percent: int) -> None:
        if percent < 0:
            self._finish(text)
            return
        self.progress.set_fraction(percent / 100.0)
        if text:
            self.message.set_text(text)

    def _on_reboot(self) -> None:
        self.message.set_text("Rebooting...")
        self._reboot_ticks = 0
        self._timer = GLib.timeout_add(75, self._reboot_tick)
        if self.serial:
            self.card_ui.app.manager.register_reopen(self.serial, self._reopened)

    def _reboot_tick(self) -> bool:
        # if the bar gets to the end twice, something probably went wrong
        if self._reboot_ticks >= 200:
            self._timer = 0
            self._finish("Reboot failed? Try unplugging/replugging/power-cycling the device.")
            return GLib.SOURCE_REMOVE
        self._reboot_ticks += 1
        self.progress.set_fraction((self._reboot_ticks % 100) / 100.0)
        return GLib.SOURCE_CONTINUE

    def _reopened(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self.set_can_close(True)
        self.close()


@Gtk.Template(string=blueprint("preset_dialog"))
class SavePresetDialog(Adw.AlertDialog):
    __gtype_name__ = "SavePresetDialog"

    entry: Adw.EntryRow = Gtk.Template.Child()

    def __init__(self, card: Card, parent: Gtk.Widget | None) -> None:
        super().__init__()
        self.card = card
        self.parent_widget = parent
        self.connect("response::save", self._on_save)
        self.present(parent)
        self.entry.grab_focus()

    @Gtk.Template.Callback()
    def on_changed(self, _entry: Adw.EntryRow) -> None:
        self.set_response_enabled("save", presets.valid_name(self.entry.get_text().strip()))

    def _on_save(self, _dialog: Adw.AlertDialog, _response: str) -> None:
        error = self.card.presets.save(self.entry.get_text().strip())
        if error:
            show_error(self.parent_widget, error)

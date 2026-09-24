# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Standard GTK widgets bound to ALSA elements.

Every widget takes a Scope; element callbacks and timers are removed
when the scope is closed (i.e. when the window section it belongs to
is destroyed or rebuilt).
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, GLib, Gtk

from vermilion.core import controls

if TYPE_CHECKING:
    from vermilion.core.card import Elem
    from vermilion.core.scope import Scope


class ElemToggle(Gtk.ToggleButton):
    """Toggle button for a boolean (or two-item enum) element.

    Texts starting with "*" name an icon of the icon theme.
    """

    def __init__(
        self,
        scope: Scope,
        elem: Elem,
        off_text: str,
        on_text: str | None = None,
        tooltip: str | None = None,
    ) -> None:
        super().__init__()
        self.elem = elem
        # "Master ... Playback Switch" on the Gen 1 is a mute, not an enable
        self.backwards = elem.name.startswith("Master") and "Playback Switch" in elem.name
        self._texts = [off_text, on_text]
        self._icons: list[Gtk.Image | None] = [None, None]
        self._load_icons()

        if tooltip:
            self.set_tooltip_text(tooltip)

        # keep the size fixed when the label changes
        max_w = max_h = 0
        for v in (0, 1):
            self._set_text(v)
            _, nat = self.get_preferred_size()
            max_w, max_h = max(max_w, nat.width), max(max_h, nat.height)
        self.set_size_request(max_w, max_h)

        self._handler = self.connect("toggled", self._on_toggled)
        scope.watch(elem, self._update)
        self._update(elem)

        if elem.volatile():
            scope.timer(1, lambda: self._update(elem))

    def _load_icons(self) -> None:
        for i, t in enumerate(self._texts):
            if t and t.startswith("*"):
                self._icons[i] = Gtk.Image(icon_name=t[1:])

    def _set_text(self, value: int) -> None:
        text = self._texts[value]
        if not text:
            return
        if text.startswith("*"):
            self.set_child(self._icons[value])
        else:
            self.set_label(text)

    def _on_toggled(self, button: Gtk.ToggleButton) -> None:
        self.elem.set_value(int(button.get_active()) ^ self.backwards)

    def _update(self, elem: Elem) -> None:
        self.set_sensitive(elem.writable())
        value = int(bool(elem.get_value())) ^ self.backwards
        with self.handler_block(self._handler):
            self.set_active(bool(value))
        self._set_text(value)

    def set_texts(self, off_text: str, on_text: str | None) -> None:
        self._texts = [off_text, on_text]
        self._load_icons()
        self._set_text(int(bool(self.elem.get_value())) ^ self.backwards)


class ElemDropDown(Gtk.DropDown):
    """Drop-down for an enumerated element, showing the selected item."""

    def __init__(self, scope: Scope, elem: Elem, tooltip: str | None = None) -> None:
        super().__init__(model=Gtk.StringList.new(elem.items()))
        self.elem = elem
        if tooltip:
            self.set_tooltip_text(tooltip)
        self._handler = self.connect("notify::selected", self._on_selected)
        scope.watch(elem, self._update)
        self._update(elem)

    def _on_selected(self, *_: object) -> None:
        pos = self.get_selected()
        if pos != Gtk.INVALID_LIST_POSITION and pos != self.elem.get_value():
            self.elem.set_value(pos)

    def _update(self, elem: Elem) -> None:
        self.set_sensitive(elem.writable())
        value = elem.get_value()
        with self.handler_block(self._handler):
            self.set_selected(value)


class ElemMenuButton(Gtk.MenuButton):
    """Menu button with radio items for an enum element.

    The label is the feature name when the first item (off) is selected,
    and the selected item otherwise.
    """

    def __init__(self, scope: Scope, elem: Elem, label: str, tooltip: str | None = None) -> None:
        super().__init__(label=label)
        self.elem = elem
        self._base_label = label
        if tooltip:
            self.set_tooltip_text(tooltip)

        menu = Gio.Menu()
        for i, item in enumerate(elem.items()):
            menu.append(item, f"elem.select({i})")
        self.set_menu_model(menu)

        self._action = Gio.SimpleAction.new_stateful(
            "select", GLib.VariantType.new("i"), GLib.Variant("i", 0)
        )
        self._action.connect("activate", self._on_activate)
        group = Gio.SimpleActionGroup()
        group.add_action(self._action)
        self.insert_action_group("elem", group)

        scope.watch(elem, self._update)
        self._update(elem)

    def _on_activate(self, _action: Gio.SimpleAction, param: GLib.Variant) -> None:
        self.elem.set_value(param.get_int32())

    def _update(self, elem: Elem) -> None:
        self.set_sensitive(elem.writable())
        value = elem.get_value()
        self._action.set_state(GLib.Variant("i", value))
        self.set_label(elem.item_name(value) if value else self._base_label)


class ElemLabel(Gtk.Label):
    """Label showing the current item of an enumerated element."""

    def __init__(self, scope: Scope, elem: Elem) -> None:
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        scope.watch(elem, self._update)
        self._update(elem)
        if elem.volatile():
            scope.timer(1, lambda: self._update(elem))

    def _update(self, elem: Elem) -> None:
        self.set_text(elem.item_name(elem.get_value()))


class ElemStatus(Gtk.Label):
    """Read-only boolean shown as a label, e.g. ("Locked", "success")."""

    STYLES = ("success", "warning", "error", "dim-label")

    def __init__(self, scope: Scope, elem: Elem, off: tuple[str, str], on: tuple[str, str]) -> None:
        super().__init__()
        self.add_css_class("heading")
        self._states = (off, on)
        scope.watch(elem, self._update)
        self._update(elem)
        if elem.volatile():
            scope.timer(1, lambda: self._update(elem))

    def _update(self, elem: Elem) -> None:
        text, style = self._states[int(bool(elem.get_value()))]
        self.set_text(text)
        for c in self.STYLES:
            self.remove_css_class(c)
        self.add_css_class(style)


class InputSelect(Gtk.ToggleButton):
    """Button selecting an input via the "Input Select" enum element."""

    def __init__(self, scope: Scope, elem: Elem, line_num: int) -> None:
        super().__init__(label=str(line_num))
        self.elem = elem
        self.line_num = line_num
        self.connect("clicked", self._on_clicked)
        scope.watch(elem, self._update)
        self._update(elem)

    def _on_clicked(self, _button: Gtk.Button) -> None:
        controls.select_input(self.elem, self.line_num)
        self._update(self.elem)

    def _update(self, elem: Elem) -> None:
        active = controls.input_select_matches(elem.item_name(elem.get_value()), self.line_num)
        self.set_active(active)
        self.set_sensitive(not active and elem.writable())


class DualToggle(Gtk.Box):
    """Two buttons for a three-state enum (Off / A / B).

    The first button enables the feature, the second switches between
    the two enabled states (speaker switching, talkback).
    """

    def __init__(self, scope: Scope, elem: Elem, label: str | None, texts: list[str]) -> None:
        """Without a label, the buttons are side by side (e.g. in a row)."""
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL if label else Gtk.Orientation.HORIZONTAL,
            spacing=5 if label else 6,
        )
        self.elem = elem
        self._texts = texts
        if label:
            self.append(Gtk.Label(label=label))
        self.button1 = Gtk.ToggleButton(label=texts[0])
        self.button2 = Gtk.ToggleButton(label=texts[2])
        self.append(self.button1)
        self.append(self.button2)
        self._h1 = self.button1.connect("toggled", self._on_toggled)
        self._h2 = self.button2.connect("toggled", self._on_toggled)
        scope.watch(elem, self._update)
        self._update(elem)

    def _on_toggled(self, _button: Gtk.ToggleButton) -> None:
        v1 = self.button1.get_active()
        v2 = self.button2.get_active()
        self.elem.set_value(int(v2) + 1 if v1 else 0)
        self.button2.set_sensitive(v1)

    def _update(self, elem: Elem) -> None:
        value = elem.get_value()
        v1 = bool(value)
        with self.button1.handler_block(self._h1), self.button2.handler_block(self._h2):
            self.button1.set_active(v1)
            self.button1.set_label(self._texts[int(v1)])
            self.button2.set_sensitive(v1)
            if v1:
                v2 = value - 1
                self.button2.set_active(bool(v2))
                self.button2.set_label(self._texts[v2 + 2])


class ElemEntry(Gtk.Entry):
    """Text entry bound to a BYTES element (custom names)."""

    def __init__(self, scope: Scope, elem: Elem, placeholder: str | None = None) -> None:
        super().__init__()
        self.elem = elem
        self.set_size_request(120, -1)
        if placeholder:
            self.set_placeholder_text(placeholder)
        self._handler = self.connect("changed", self._on_changed)
        scope.watch(elem, self._update)
        self._update(elem)

    def _on_changed(self, _entry: Gtk.Editable) -> None:
        self.elem.set_bytes(self.get_text())

    def _update(self, elem: Elem) -> None:
        self.set_sensitive(elem.writable())
        text = elem.get_str()
        if text != self.get_text():
            with self.handler_block(self._handler):
                self.set_text(text)


class ElemCheck(Gtk.CheckButton):
    """Check button bound to a boolean element."""

    def __init__(self, scope: Scope, elem: Elem, tooltip: str | None = None) -> None:
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.elem = elem
        if tooltip:
            self.set_tooltip_text(tooltip)
        self._handler = self.connect("toggled", self._on_toggled)
        scope.watch(elem, self._update)
        self._update(elem)

    def _on_toggled(self, button: Gtk.ToggleButton) -> None:
        self.elem.set_value(1 if button.get_active() else 0)

    def _update(self, elem: Elem) -> None:
        with self.handler_block(self._handler):
            self.set_active(bool(elem.get_value()))


class VisibilityToggle(Gtk.Button):
    """Show/hide button (an eye, open when shown) bound to the enable
    element of a port."""

    def __init__(self, scope: Scope, elem: Elem) -> None:
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.add_css_class("flat")
        self.add_css_class("circular")
        self.elem = elem
        self.connect("clicked", lambda _b: elem.set_value(0 if elem.get_value() else 1))
        scope.watch(elem, self._update)
        self._update(elem)

    def _update(self, elem: Elem) -> None:
        shown = bool(elem.get_value())
        self.set_icon_name("view-reveal-symbolic" if shown else "view-conceal-symbolic")
        self.set_tooltip_text(
            "Shown in Routing, Mixer and Levels; click to hide"
            if shown
            else "Hidden from Routing, Mixer and Levels; click to show"
        )


class LinkToggle(Gtk.ToggleButton):
    """Stereo link toggle: pressed when the pair is linked."""

    def __init__(
        self, scope: Scope, elem: Elem, tooltip: str | None = "Link as stereo pair"
    ) -> None:
        super().__init__(
            icon_name="insert-link-symbolic",
            tooltip_text=tooltip,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            css_classes=["flat"],
        )
        self.elem = elem
        self._handler = self.connect("toggled", lambda b: elem.set_value(int(b.get_active())))
        scope.watch(elem, self._update)
        self._update(elem)

    def _update(self, elem: Elem) -> None:
        with self.handler_block(self._handler):
            self.set_active(bool(elem.get_value()))


# Adwaita rows are final types: they are bound to elements by functions
# instead of subclasses.


class ElemComboRow(Adw.ComboRow):
    """Combo row for an enumerated element.

    With presets [(label, value)], rows map to arbitrary element values; a
    value not among them is shown as an extra "custom" row, labelled by
    custom_label(value).
    """

    def __init__(
        self,
        scope: Scope,
        elem: Elem,
        title: str,
        subtitle: str | None = None,
        presets: list[tuple[str, int]] | None = None,
        custom_label: Callable[[int], str] | None = None,
    ) -> None:
        labels = [label for label, _ in presets] if presets else elem.items()
        super().__init__(title=title, subtitle=subtitle or "", model=Gtk.StringList.new(labels))
        self.elem = elem
        self._values = [value for _, value in presets] if presets else None
        self._custom_label = custom_label
        self._custom = False
        self._handler = self.connect("notify::selected", self._on_selected)
        scope.watch(elem, self._update)
        self._update(elem)

    def _on_selected(self, *_: object) -> None:
        pos = self.get_selected()
        if pos == Gtk.INVALID_LIST_POSITION:
            return
        if self._values is None:
            value = pos
        elif pos < len(self._values):
            value = self._values[pos]
        else:
            return
        if value != self.elem.get_value():
            self.elem.set_value(value)

    def _update(self, elem: Elem) -> None:
        self.set_sensitive(elem.writable())
        value = elem.get_value()
        values = self._values
        model = self.get_model()
        assert isinstance(model, Gtk.StringList)
        with self.handler_block(self._handler):
            if values is None:
                self.set_selected(value)
            elif value in values:
                if self._custom:
                    model.remove(len(values))
                    self._custom = False
                self.set_selected(values.index(value))
            else:
                label = self._custom_label(value) if self._custom_label else str(value)
                model.splice(len(values), 1 if self._custom else 0, [label])
                self._custom = True
                self.set_selected(len(values))


def elem_switch_row(
    scope: Scope, elem: Elem, title: str, subtitle: str | None = None
) -> Adw.SwitchRow:
    """Switch row for a boolean element (a function: Adw.SwitchRow can't
    be subclassed)."""
    row = Adw.SwitchRow(title=title, subtitle=subtitle or "")

    def update(elem: Elem) -> None:
        row.set_sensitive(elem.writable())
        with row.handler_block(handler):
            row.set_active(bool(elem.get_value()))

    handler = row.connect("notify::active", lambda *_: elem.set_value(int(row.get_active())))
    scope.watch(elem, update)
    update(elem)
    return row


class ElemEntryRow(Adw.EntryRow):
    """Entry row for a BYTES element (custom names)."""

    def __init__(self, scope: Scope, elem: Elem, title: str) -> None:
        super().__init__(title=title)
        self._handler = self.connect("changed", lambda _r: elem.set_bytes(self.get_text()))
        scope.watch(elem, self._update)
        self._update(elem)

    def _update(self, elem: Elem) -> None:
        self.set_sensitive(elem.writable())
        text = elem.get_str()
        if text != self.get_text():
            with self.handler_block(self._handler):
                self.set_text(text)

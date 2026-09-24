# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""A titled group that can be folded away."""

from gi.repository import Gtk

from vermilion.ui.resources import blueprint


@Gtk.Template(string=blueprint("controls_group"))
class ControlsGroup(Gtk.Box):
    """A heading above the child; as large as the child. The heading is an
    expander that shows or hides the child."""

    __gtype_name__ = "ControlsGroup"

    expander: Gtk.Expander = Gtk.Template.Child()
    title: Gtk.Label = Gtk.Template.Child()
    content: Gtk.Box = Gtk.Template.Child()

    def __init__(self, title: str, child: Gtk.Widget) -> None:
        super().__init__()
        self.title.set_text(title)
        child.set_hexpand(True)
        self.content.append(child)
        # as wide as the content: the expanding controls inside fill the
        # group, not the page
        self.set_hexpand(False)
        self.set_halign(Gtk.Align.START)

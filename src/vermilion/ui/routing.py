# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Routing window: drag-and-drop connections between sources and sinks."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import cairo
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk

from vermilion.core.constants import PC, UNAVAILABLE_MIXER
from vermilion.core.features.visibility import PortVisibility
from vermilion.core.ports import Port, RoutingSnk, RoutingSrc
from vermilion.ui import routing_draw as rd
from vermilion.ui.resources import blueprint
from vermilion.ui.widgets.elem import ElemToggle

if TYPE_CHECKING:
    from vermilion.core.card import Elem
    from vermilion.ui.card_window import CardUI

DRAG_NONE, DRAG_SRC, DRAG_SNK = 0, 1, 2

LABEL_WIDTH_MONO = 3
LABEL_WIDTH_STEREO = 4


def _event_widget(controller: Gtk.EventController) -> Gtk.Widget:
    """The widget of an event controller (set while it handles events)."""
    widget = controller.get_widget()
    assert widget is not None
    return widget


class Socket(Gtk.Box):
    """The socket of a port: round, or for a stereo pair a pill of two
    (horizontal for the mixer and DSP ports at the top/bottom); drawn by
    style.css."""

    def __init__(self) -> None:
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.add_css_class("socket")
        self.add_css_class("route-label")

    def set_shape(self, linked: bool, port_category: int) -> None:
        for name in ("socket-stereo-h", "socket-stereo-v"):
            self.remove_css_class(name)
        if linked:
            horizontal = rd.is_mixer(port_category)
            self.add_css_class("socket-stereo-h" if horizontal else "socket-stereo-v")


def _set_label(
    label: Gtk.Label,
    text: str,
    available: bool = True,
    tooltip: str | None = None,
    markup: str | None = None,
) -> None:
    if markup is not None:
        label.set_markup(markup)
        label.set_tooltip_text(None)
    elif not available:
        label.set_markup(f'<span alpha="50%"><s>{GLib.markup_escape_text(text)}</s></span>')
        label.set_tooltip_text(tooltip)
    else:
        label.set_text(text)
        label.set_use_markup(False)
        label.set_tooltip_text(None)


def _center(widget: Gtk.Widget, target: Gtk.Widget) -> tuple[float, float]:
    ok, p = widget.compute_point(
        target, Graphene.Point.alloc().init(widget.get_width() / 2, widget.get_height() / 2)
    )
    return (p.x, p.y) if ok else (0.0, 0.0)


def _union_bounds(widgets: Sequence[Gtk.Widget | None], target: Gtk.Widget) -> Graphene.Rect | None:
    rect = None
    for w in widgets:
        if w is None or w.get_parent() is None:
            return None
        ok, r = w.compute_bounds(target)
        if not ok:
            return None
        rect = r if rect is None else rect.union(r)
    return rect


@Gtk.Template(string=blueprint("routing_group"))
class RoutingGroup(Gtk.Box):
    __gtype_name__ = "RoutingGroup"

    heading: Gtk.Label = Gtk.Template.Child()
    card: Gtk.Box = Gtk.Template.Child()
    side_box: Gtk.Box = Gtk.Template.Child()
    grid: Gtk.Grid = Gtk.Template.Child()

    def __init__(
        self, title: str, tooltip: str | None, horizontal: bool, below: bool = False
    ) -> None:
        """A horizontal group has a port per column (the mixer and DSP ports
        at the top and bottom); the heading of one at the bottom is below
        it, so that the lines don't cross it."""
        super().__init__()
        self.title = title
        self.heading.set_text(title)
        self.heading.set_tooltip_text(tooltip)
        if horizontal:
            self.set_halign(Gtk.Align.CENTER)
            self.set_valign(Gtk.Align.END if not below else Gtk.Align.START)
            self.grid.set_column_homogeneous(True)
        else:
            self.set_halign(Gtk.Align.FILL)
            self.set_valign(Gtk.Align.CENTER)
            self.set_vexpand(True)
            self.card.set_orientation(Gtk.Orientation.VERTICAL)
            self.grid.set_row_homogeneous(True)
        if below:
            self.reorder_child_after(self.heading, self.card)

    def add_row_label(self, label: Gtk.Label) -> None:
        self.side_box.append(label)
        self.side_box.set_visible(True)


class _PortWidgets:
    """Socket and label (or talkback button) of a port."""

    def __init__(
        self, socket: Socket, label: Gtk.Label, talkback: ElemToggle | None = None
    ) -> None:
        self.socket = socket
        self.label = label
        self.talkback = talkback


@Gtk.Template(string=blueprint("routing_panel"))
class RoutingPanel(Gtk.Box):
    __gtype_name__ = "RoutingPanel"

    overlay: Gtk.Overlay = Gtk.Template.Child()
    routing_grid: Gtk.Grid = Gtk.Template.Child()
    src_label: Gtk.Label = Gtk.Template.Child()
    lines: Gtk.DrawingArea = Gtk.Template.Child()
    drag_line: Gtk.DrawingArea = Gtk.Template.Child()

    def __init__(self, card_ui: CardUI) -> None:
        super().__init__()
        self.card_ui = card_ui
        self.card = card = card_ui.card
        self.scope = card_ui.scope

        self.widgets: dict[Port, _PortWidgets] = {}
        self.hovered_src: RoutingSrc | None = None
        self.hovered_snk: RoutingSnk | None = None
        self.drag_type = DRAG_NONE
        self.src_drag: RoutingSrc | None = None
        self.snk_drag: RoutingSnk | None = None
        self.drag_x = self.drag_y = -1.0

        self._setup_presets()
        self._create_groups()
        self._create_widgets()

        self.lines.set_draw_func(self._draw_lines)
        self.drag_line.set_draw_func(self._draw_drag_line)

        s = self.scope
        s.connect(
            card,
            "port-visibility-changed",
            lambda _c, pc, is_src: self._on_port_visibility(pc, is_src),
        )
        s.connect(card, "stereo-changed", lambda _c: self._on_stereo_changed())
        s.connect(card, "routing-changed", lambda _c: self.queue_draw_lines())
        # the colours follow the light or dark style, the widths the high
        # contrast one
        style = Adw.StyleManager.get_default()
        s.connect(style, "notify::dark", lambda *_a: self.queue_draw_lines())
        s.connect(style, "notify::high-contrast", lambda *_a: self.queue_draw_lines())
        s.connect(card, "monitor-groups-state-changed", lambda _c: self._update_snk_labels())
        s.connect(card, "availability-changed", lambda _c: self._update_all_labels())

        self._update_all_labels()
        self._update_section_visibility()
        self._setup_controllers()

    # construction

    def _setup_presets(self) -> None:
        group = Gio.SimpleActionGroup()
        action = Gio.SimpleAction.new("preset", GLib.VariantType.new("s"))
        action.connect(
            "activate",
            lambda _a, p: self.card.apply_routing_preset(p.get_string()),
        )
        group.add_action(action)

        # stereo link of the port under the context menu
        self._menu_link: Elem | None = None
        toggle = Gio.SimpleAction.new("toggle-link", None)
        toggle.connect("activate", lambda *_: self._toggle_menu_link())
        group.add_action(toggle)
        self.insert_action_group("routing", group)

    def _toggle_menu_link(self) -> None:
        if self._menu_link:
            self._menu_link.set_value(0 if self._menu_link.get_value() else 1)

    def _create_groups(self) -> None:
        card = self.card
        grid = self.routing_grid
        has_dsp = bool(card.routing_in_count[PC.DSP])
        H, V = True, False

        self.src_groups: dict[int, RoutingGroup] = {
            PC.HW: RoutingGroup(
                "Hardware Inputs",
                "Hardware Inputs are the physical inputs on the interface",
                V,
            ),
            PC.PCM: RoutingGroup(
                "PCM Outputs",
                "PCM Outputs are the digital audio channels sent from the PC to the "
                "interface over USB, used for audio playback",
                V,
            ),
            PC.MIX: RoutingGroup(
                "Mixer Outputs",
                "Mixer Outputs are used to send audio from the mixer",
                H,
                below=True,
            ),
        }
        self.snk_groups: dict[int, RoutingGroup] = {
            PC.PCM: RoutingGroup(
                "PCM Inputs",
                "PCM Inputs are the digital audio channels sent from the interface "
                "to the PC over USB, use for audio recording",
                V,
            ),
            PC.HW: RoutingGroup(
                "Hardware Outputs",
                "Hardware Outputs are the physical outputs on the interface",
                V,
            ),
        }
        if not card.has_fixed_mixer_inputs:
            self.snk_groups[PC.MIX] = RoutingGroup(
                "Mixer Inputs",
                "Mixer Inputs are used to mix multiple audio channels together",
                H,
            )
        if has_dsp:
            self.snk_groups[PC.DSP] = RoutingGroup(
                "DSP Inputs",
                "DSP Inputs are used to send audio to the DSP, which is used for "
                "features such as the input level meters, Air mode, and Autogain",
                H,
            )
            self.src_groups[PC.DSP] = RoutingGroup(
                "DSP Outputs",
                "DSP Outputs are used to send audio from the DSP after it has done its processing",
                H,
                below=True,
            )

        dsp_col = 1 if has_dsp else 0
        mix_col = dsp_col + 1
        right_col = mix_col + 1

        # keep spacing even when the mixer column is empty
        spacer = Gtk.Box()
        spacer.set_size_request(200, 1)
        grid.attach(spacer, mix_col, 0, 1, 1)

        grid.attach(self.src_groups[PC.HW], 0, 1, 1, 1)
        grid.attach(self.src_groups[PC.PCM], 0, 2, 1, 1)
        grid.attach(self.snk_groups[PC.PCM], right_col, 1, 1, 1)
        grid.attach(self.snk_groups[PC.HW], right_col, 2, 1, 1)
        if has_dsp:
            grid.attach(self.snk_groups[PC.DSP], dsp_col, 0, 1, 1)
            grid.attach(self.src_groups[PC.DSP], dsp_col, 3, 1, 1)
        if PC.MIX in self.snk_groups:
            grid.attach(self.snk_groups[PC.MIX], mix_col, 0, 1, 1)
        grid.attach(self.src_groups[PC.MIX], mix_col, 3, 1, 1)

        self.snk_label = Gtk.Label(
            justify=Gtk.Justification.CENTER,
            label="Sinks\n↓" if card.has_fixed_mixer_inputs else "← Sinks\n↓",
        )
        grid.attach(self.snk_label, right_col, 0, 1, 1)

        if card.has_talkback:
            label = Gtk.Label(label="Talkback")
            label.set_tooltip_text(
                "Mixer Outputs with Talkback enabled will have the level of Mixer "
                "Input 25 internally raised and lowered when the Talkback control "
                "is turned On and Off."
            )
            self.src_groups[PC.MIX].add_row_label(label)
            # as high as the talkback buttons, so that it is in line with them
            self._talkback_row = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.VERTICAL)
            self._talkback_row.add_widget(label)

    def _make_label(self, text: str, port_category: int, linked: bool, xalign: float) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.add_css_class("route-label")
        if rd.is_mixer(port_category):
            label.set_width_chars(LABEL_WIDTH_STEREO if linked else LABEL_WIDTH_MONO)
        else:
            label.set_hexpand(True)
            label.set_halign(Gtk.Align.FILL)
            label.set_xalign(xalign)
            # as high as a stereo socket, so that all groups have the same rows
            label.add_css_class("routing-port")
        return label

    def _create_widgets(self) -> None:
        card = self.card
        s = self.scope

        for snk in card.routing_snks:
            pc = snk.port_category
            if pc == PC.MIX and card.has_fixed_mixer_inputs:
                continue
            self._add_widgets(
                snk,
                _PortWidgets(
                    Socket(),
                    self._make_label(snk.display_name_formatted, pc, snk.is_linked, 0.0),
                ),
            )
            s.connect(snk, "name-changed", self._update_snk_label)

        if not card.routing_out_count[PC.MIX]:
            return

        for src in card.routing_srcs[1:]:
            talkback = None
            if src.port_category == PC.MIX and card.has_talkback and src.talkback_elem:
                name = src.talkback_label
                talkback = ElemToggle(s, src.talkback_elem, name, name)
                self._talkback_row.add_widget(talkback)
            self._add_widgets(
                src,
                _PortWidgets(
                    Socket(),
                    self._make_label(
                        src.display_name_formatted, src.port_category, src.is_linked, 1.0
                    ),
                    talkback,
                ),
            )
            s.connect(src, "name-changed", self._update_src_label)

        for pc in (PC.DSP, PC.MIX, PC.HW, PC.PCM):
            self.arrange_srcs(pc)
            self.arrange_snks(pc)

    def _add_widgets(self, port: Port, widgets: _PortWidgets) -> None:
        self.widgets[port] = widgets
        widgets.socket.set_shape(port.is_linked, port.port_category)

        def link_changed(_e: Elem, port: Port = port) -> None:
            self._link_changed(port)

        for elem in (port.stereo_link_elem, port.stereo_name_elem):
            if elem:
                self.scope.watch(elem, link_changed)

    def _ports[P: Port](self, kind: type[P]) -> list[P]:
        """The sources or sinks shown in the window."""
        return [p for p in self.widgets if isinstance(p, kind)]

    # grid arrangement

    def arrange_srcs(self, pc: int) -> None:
        group = self.src_groups.get(pc)
        if not group:
            return
        grid = group.grid
        horiz = rd.is_mixer(pc)
        pos = 0
        for src in self._ports(RoutingSrc):
            w = self.widgets[src]
            if src.port_category != pc:
                continue
            for widget in (w.socket, w.label, w.talkback):
                if widget and widget.get_parent() is grid:
                    grid.remove(widget)
            if not src.visible:
                continue
            if horiz:
                grid.attach(w.socket, pos, 0, 1, 1)
                grid.attach(w.talkback or w.label, pos, 1, 1, 1)
            else:
                grid.attach(w.label, 0, pos, 1, 1)
                grid.attach(w.socket, 1, pos, 1, 1)
            pos += 1
        self.queue_draw_lines()

    def arrange_snks(self, pc: int) -> None:
        group = self.snk_groups.get(pc)
        if not group:
            return
        grid = group.grid
        horiz = rd.is_mixer(pc)
        pos = 0
        for snk in self._ports(RoutingSnk):
            w = self.widgets[snk]
            if snk.elem.port_category != pc:
                continue
            for widget in (w.socket, w.label):
                if widget.get_parent() is grid:
                    grid.remove(widget)
            if not snk.visible:
                continue
            if horiz:
                grid.attach(w.label, pos, 0, 1, 1)
                grid.attach(w.socket, pos, 1, 1, 1)
            else:
                grid.attach(w.socket, 0, pos, 1, 1)
                grid.attach(w.label, 1, pos, 1, 1)
            pos += 1
        self.queue_draw_lines()

    def _update_section_visibility(self) -> None:
        card = self.card
        for pc, group in self.src_groups.items():
            group.set_visible(not PortVisibility.all_hidden(card.routing_srcs, pc))
        for pc, group in self.snk_groups.items():
            group.set_visible(not PortVisibility.all_hidden(card.routing_snks, pc))

        hw_pcm_src = not PortVisibility.all_hidden(
            card.routing_srcs, PC.HW
        ) or not PortVisibility.all_hidden(card.routing_srcs, PC.PCM)
        mix_dsp_src = not PortVisibility.all_hidden(
            card.routing_srcs, PC.MIX
        ) or not PortVisibility.all_hidden(card.routing_srcs, PC.DSP)
        self.src_label.set_visible(hw_pcm_src or mix_dsp_src)
        self.src_label.set_text(
            "↑\nSources →"
            if hw_pcm_src and mix_dsp_src
            else "↑\nSources"
            if hw_pcm_src
            else "Sources →"
        )

        hw_pcm_snk = not PortVisibility.all_hidden(
            card.routing_snks, PC.HW
        ) or not PortVisibility.all_hidden(card.routing_snks, PC.PCM)
        mix_snk = not card.has_fixed_mixer_inputs and not PortVisibility.all_hidden(
            card.routing_snks, PC.MIX
        )
        mix_dsp_snk = mix_snk or not PortVisibility.all_hidden(card.routing_snks, PC.DSP)
        self.snk_label.set_visible(hw_pcm_snk or mix_dsp_snk)
        self.snk_label.set_text(
            "← Sinks\n↓" if hw_pcm_snk and mix_dsp_snk else "Sinks\n↓" if hw_pcm_snk else "← Sinks"
        )

    # labels

    def _update_src_label(self, src: RoutingSrc) -> None:
        w = self.widgets.get(src)
        if not w:
            return
        name = src.stereo_aware_name
        available, tooltip = src.availability()
        _set_label(w.label, name, available, tooltip)
        if rd.is_mixer(src.port_category):
            w.label.set_width_chars(LABEL_WIDTH_STEREO if src.is_linked else LABEL_WIDTH_MONO)
        if w.talkback:
            label = src.talkback_label
            w.talkback.set_texts(label, label)

    def _update_snk_label(self, snk: RoutingSnk) -> None:
        w = self.widgets.get(snk)
        if not w:
            return
        name = snk.stereo_aware_name
        available, tooltip = snk.availability()
        if not available:
            _set_label(w.label, name, False, tooltip)
            return

        indicator = snk.monitor_indicator
        esc = GLib.markup_escape_text(name)
        if indicator == "main":
            _set_label(
                w.label, name, markup=(f'{esc} <span color="#26a269"><small>Main</small></span>')
            )
        elif indicator == "alt":
            _set_label(
                w.label, name, markup=(f'{esc} <span color="#e66100"><small>Alt</small></span>')
            )
        elif indicator == "strike":
            _set_label(w.label, name, markup=f"<s>{esc}</s>")
        else:
            _set_label(w.label, name)

    def _update_snk_labels(self) -> None:
        for snk in self._ports(RoutingSnk):
            self._update_snk_label(snk)
        self.queue_draw_lines()

    def _update_all_labels(self) -> None:
        for src in self._ports(RoutingSrc):
            self._update_src_label(src)
        self._update_snk_labels()

        available = self.card.mixer_available
        tooltip = UNAVAILABLE_MIXER
        if PC.MIX in self.snk_groups:
            group = self.snk_groups[PC.MIX]
            _set_label(group.heading, group.title, available, tooltip)
        _set_label(
            self.src_groups[PC.MIX].heading, self.src_groups[PC.MIX].title, available, tooltip
        )

    def _link_changed(self, port: Port) -> None:
        w = self.widgets.get(port)
        if not w:
            return
        w.socket.set_shape(port.is_linked, port.port_category)
        if isinstance(port, RoutingSrc):
            self._update_src_label(port)
            self.arrange_srcs(port.port_category)
        elif isinstance(port, RoutingSnk):
            self._update_snk_label(port)
            self.arrange_snks(port.port_category)

    # model notifications

    def _on_port_visibility(self, pc: int, is_src: bool) -> None:
        if is_src:
            self.arrange_srcs(pc)
        else:
            self.arrange_snks(pc)
        self._update_section_visibility()

    def _on_stereo_changed(self) -> None:
        self._update_section_visibility()
        for src in self._ports(RoutingSrc):
            w = self.widgets[src]
            if w.talkback and src.should_display:
                label = src.talkback_label
                w.talkback.set_texts(label, label)
        self.queue_draw_lines()

    def queue_draw_lines(self) -> None:
        self.lines.queue_draw()

    # hit testing

    def _bounds(self, port: Port, target: Gtk.Widget) -> Graphene.Rect | None:
        w = self.widgets.get(port)
        if not w or w.socket.get_parent() is None:
            return None
        if not w.talkback:
            return _union_bounds([w.socket, w.label], target)
        rect = _union_bounds([w.socket, w.talkback], target)
        if rect is None:
            return None
        # extend to the top of the grid cell
        parent = w.socket.get_parent()
        ok, p = (
            w.socket.compute_point(parent, Graphene.Point.alloc().init(0, 0))
            if parent
            else (False, None)
        )
        if ok and p and p.y > 0:
            rect = Graphene.Rect.alloc().init(
                rect.get_x(), rect.get_y() - p.y, rect.get_width(), rect.get_height() + p.y
            )
        return rect

    def _port_at[P: Port](self, kind: type[P], target: Gtk.Widget, x: float, y: float) -> P | None:
        """The source or sink at a position."""
        point = Graphene.Point.alloc().init(x, y)
        for port in self._ports(kind):
            if not port.enabled or not port.should_display:
                continue
            rect = self._bounds(port, target)
            if rect and rect.contains_point(point):
                return port
        return None

    def _src_at(self, target: Gtk.Widget, x: float, y: float) -> RoutingSrc | None:
        return self._port_at(RoutingSrc, target, x, y)

    def _snk_at(self, target: Gtk.Widget, x: float, y: float) -> RoutingSnk | None:
        return self._port_at(RoutingSnk, target, x, y)

    # hover highlight

    def _widgets_for(self, port: Port | None) -> list[Gtk.Widget]:
        """Socket and label of a port, and of its partner if linked."""
        if port is None:
            return []
        pair = [port, port.partner] if port.is_linked else [port]
        return [
            widget
            for p in pair
            if p and (w := self.widgets.get(p))
            for widget in (w.socket, w.label)
        ]

    def _set_hover(self, src: RoutingSrc | None, snk: RoutingSnk | None) -> None:
        if src is self.hovered_src and snk is self.hovered_snk:
            return
        for obj in (self.hovered_src, self.hovered_snk):
            for w in self._widgets_for(obj):
                w.remove_css_class("route-label-hover")
        self.hovered_src, self.hovered_snk = src, snk
        for obj in (src, snk):
            for w in self._widgets_for(obj):
                w.add_css_class("route-label-hover")
        self.queue_draw_lines()

    # controllers

    def _setup_controllers(self) -> None:
        ov = self.overlay

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda _c: self._set_hover(None, None))
        ov.add_controller(motion)

        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        ov.add_controller(click)

        right_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right_click.connect("released", self._on_right_click)
        ov.add_controller(right_click)

        drag = Gtk.DragSource(actions=Gdk.DragAction.COPY)
        drag.connect("prepare", self._on_drag_prepare)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-end", self._on_drag_end)
        ov.add_controller(drag)

        drop = Gtk.DropTarget.new(int, Gdk.DragAction.COPY)
        drop.connect("motion", self._on_drop_motion)
        drop.connect("leave", self._on_drop_leave)
        drop.connect("drop", self._on_drop)
        ov.add_controller(drop)

        drop_motion = Gtk.DropControllerMotion()
        drop_motion.connect("enter", self._on_drag_motion)
        drop_motion.connect("motion", self._on_drag_motion)
        self.routing_grid.add_controller(drop_motion)

    def _on_motion(self, controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        if self.drag_type != DRAG_NONE:
            return
        w = _event_widget(controller)
        src = self._src_at(w, x, y)
        snk = None if src else self._snk_at(w, x, y)
        self._set_hover(src, snk)

    def _on_click(self, gesture: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        w = _event_widget(gesture)
        src = self._src_at(w, x, y)
        if src:
            src.disconnect_sinks()
            return
        snk = self._snk_at(w, x, y)
        if snk:
            snk.disconnect_source()

    def _on_right_click(self, gesture: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        widget = _event_widget(gesture)
        src = self._src_at(widget, x, y)
        snk = None if src else self._snk_at(widget, x, y)

        anchor: Gtk.Widget
        if src and src.partner:
            link = src.stereo_link_elem
            linked = src.is_linked
            anchor = self.widgets[src].label
        elif snk and snk.partner:
            link = snk.stereo_link_elem
            linked = snk.is_linked
            anchor = self.widgets[snk].label
        else:
            return
        if not link:
            return

        self._menu_link = link
        menu = Gio.Menu()
        menu.append(
            "Unlink Stereo Pair" if linked else "Link as Stereo Pair", "routing.toggle-link"
        )
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(anchor)

        def unparent() -> bool:
            popover.unparent()
            return GLib.SOURCE_REMOVE

        popover.connect("closed", lambda _p: GLib.idle_add(unparent))
        popover.popup()

    def _on_drag_prepare(
        self, source: Gtk.DragSource, x: float, y: float
    ) -> Gdk.ContentProvider | None:
        w = _event_widget(source)
        src = self._src_at(w, x, y)
        if src:
            self.drag_type, self.src_drag, self.snk_drag = DRAG_SRC, src, None
            return Gdk.ContentProvider.new_for_value(src.id)
        snk = self._snk_at(w, x, y)
        if snk:
            self.drag_type, self.src_drag, self.snk_drag = DRAG_SNK, None, snk
            return Gdk.ContentProvider.new_for_value(0x8000 | snk.idx)
        return None

    def _on_drag_begin(self, source: Gtk.DragSource, _drag: Gdk.Drag) -> None:
        source.set_icon(Gdk.Paintable.new_empty(1, 1), 0, 0)

    def _on_drag_end(self, _source: Gtk.DragSource, _drag: Gdk.Drag, _delete: bool) -> None:
        self.drag_type = DRAG_NONE
        self.src_drag = self.snk_drag = None
        if self.drag_x >= 0 and self.drag_y >= 0:
            grid = self.routing_grid
            src = self._src_at(grid, self.drag_x, self.drag_y)
            snk = None if src else self._snk_at(grid, self.drag_x, self.drag_y)
            self.hovered_src = self.hovered_snk = None
            self._set_hover(src, snk)
        self.drag_x = self.drag_y = -1.0
        self.drag_line.queue_draw()
        self.queue_draw_lines()

    def _on_drop_motion(self, target: Gtk.DropTarget, x: float, y: float) -> Gdk.DragAction:
        w = _event_widget(target)
        if self.drag_type == DRAG_SRC:
            snk = self._snk_at(w, x, y)
            if snk and snk.accepts(self.src_drag):
                self.snk_drag = snk
                self._set_hover(None, snk)
                self.drag_line.queue_draw()
                return Gdk.DragAction.COPY
            self.snk_drag = None
            self._set_hover(None, None)
        elif self.drag_type == DRAG_SNK:
            src = self._src_at(w, x, y)
            if src and self.snk_drag and self.snk_drag.accepts(src):
                self.src_drag = src
                self._set_hover(src, None)
                self.drag_line.queue_draw()
                return Gdk.DragAction.COPY
            self.src_drag = None
            self._set_hover(None, None)
        self.drag_line.queue_draw()
        return Gdk.DragAction(0)

    def _on_drop_leave(self, _target: Gtk.DropTarget) -> None:
        if self.drag_type == DRAG_SRC:
            self.snk_drag = None
        elif self.drag_type == DRAG_SNK:
            self.src_drag = None
        self._set_hover(None, None)
        self.drag_line.queue_draw()

    def _on_drop(self, target: Gtk.DropTarget, _value: GObject.Value, x: float, y: float) -> bool:
        w = _event_widget(target)
        if self.drag_type == DRAG_SRC and self.src_drag:
            snk = self._snk_at(w, x, y)
            if snk:
                return snk.connect_source(self.src_drag)
        if self.drag_type == DRAG_SNK and self.snk_drag:
            src = self._src_at(w, x, y)
            if src:
                return self.snk_drag.connect_source(src)
        return False

    def _on_drag_motion(self, _controller: Gtk.DropControllerMotion, x: float, y: float) -> None:
        self.drag_x, self.drag_y = x, y

        # scroll the window along with the mouse
        sw = self.get_ancestor(Gtk.ScrolledWindow)
        child = sw.get_child() if isinstance(sw, Gtk.ScrolledWindow) else None
        if isinstance(sw, Gtk.ScrolledWindow) and child:
            hadj, vadj = sw.get_hadjustment(), sw.get_vadjustment()
            w = hadj.get_upper() - hadj.get_page_size()
            h = vadj.get_upper() - vadj.get_page_size()
            rel_w = hadj.get_upper() - sw.get_width() + child.get_width() - 100
            rel_h = vadj.get_upper() - sw.get_height() + child.get_height() - 100
            if rel_w > 0 and rel_h > 0:
                px = min(max(x - 50, 0), rel_w)
                py = min(max(y - 50, 0), rel_h)
                hadj.set_value(px / rel_w * w)
                vadj.set_value(py / rel_h * h)

        self.drag_line.queue_draw()
        self.queue_draw_lines()

    # drawing

    def _center(self, port: Port, target: Gtk.Widget) -> tuple[float, float] | None:
        """Where lines connect to a port (a side of the socket if linked)."""
        left = port.left if port.is_linked else port
        w = self.widgets.get(left) if left else None
        if w is None or w.socket.get_parent() is None:
            return None
        x, y = _center(w.socket, target)
        if port.is_linked:
            x, y = self._stereo_offset(w.socket, port.port_category, port.is_left, x, y)
        if rd.is_mixer(port.port_category):
            y += 1
        return x, y

    @staticmethod
    def _stereo_offset(
        socket: Gtk.Widget, pc: int, is_left: bool, x: float, y: float
    ) -> tuple[float, float]:
        if rd.is_mixer(pc):
            x += -socket.get_width() * 0.25 if is_left else socket.get_width() * 0.25
        else:
            y += -socket.get_height() * 0.25 if is_left else socket.get_height() * 0.25
        return x, y

    def _dragging_snk(self, snk: RoutingSnk) -> bool:
        d = self.snk_drag
        return (
            self.drag_type != DRAG_NONE
            and d is not None
            and (d is snk or (d.is_linked and d.partner is snk))
        )

    def _draw_lines(
        self, area: Gtk.DrawingArea, cr: cairo.Context[cairo.Surface], _width: int, _height: int
    ) -> None:
        card = self.card
        cr.set_line_cap(cairo.LineCap.ROUND)
        painter = rd.Painter(cr)
        snks = [s for s in card.routing_snks if s in self.widgets]

        # glows behind all lines
        if card.routing_levels:
            connected = set()
            for snk in snks:
                if not snk.enabled:
                    continue
                src = card.src(snk.effective_source_idx)
                if not src or src.id == 0 or not src.enabled:
                    continue
                connected.add(src)
                if self._dragging_snk(snk):
                    continue
                level = card.src_level_db(src)
                if level < rd.GLOW_MIN_DB:
                    continue
                a = self._center(src, area)
                b = self._center(snk, area)
                if a and b:
                    painter.cable_glow(
                        rd.Cable(a, src.port_category, b, snk.elem.port_category), level
                    )

            for src in self._ports(RoutingSrc):
                if src in connected or not src.enabled:
                    continue
                level = card.src_level_db(src)
                if level < rd.GLOW_MIN_DB:
                    continue
                a = self._center(src, area)
                if a:
                    painter.source_glow(a, level)

        # the routing lines; with a port under the pointer its cables are
        # emphasised and drawn last, the others fade
        hovered = {
            p
            for port in (self.hovered_src, self.hovered_snk)
            if port
            for p in ([port, port.partner] if port.is_linked else [port])
            if p
        }
        width = rd.line_width()
        cables = []
        for snk in snks:
            if not snk.enabled:
                continue
            src = card.src(snk.effective_source_idx)
            if not src or src.id == 0 or not src.enabled:
                continue
            a = self._center(src, area)
            b = self._center(snk, area)
            if a and b:
                cables.append((src in hovered or snk in hovered, src, snk, a, b))
        # steep cables last: they cross the bundles of horizontal ones and
        # would otherwise be cut into dashes by the gaps of the casing
        cables.sort(key=lambda c: (c[0], abs(c[4][1] - c[3][1]) / (abs(c[4][0] - c[3][0]) + 1)))

        for emphasised, src, snk, a, b in cables:
            alpha = 1.0 if emphasised or not hovered else rd.FADED_ALPHA
            # a sink being reconnected: faint and dotted
            dragging = self._dragging_snk(snk)
            if dragging:
                alpha = min(alpha, 0.5)
            cr.set_dash(rd.DASH_DOTTED if dragging else [])
            painter.cable(
                rd.Cable(a, src.port_category, b, snk.elem.port_category),
                rd.line_colour(snk.idx),
                width=width + (rd.HIGHLIGHT_EXTRA_WIDTH if emphasised else 0),
                alpha=alpha,
                casing=0 if dragging or alpha < 1 else rd.CASING,
            )

        # arrows for connections to/from hidden ports
        cr.set_dash([])
        srcs_with_hidden_snk = set()
        for snk in snks:
            src = card.src(snk.effective_source_idx)
            if not src or src.id == 0:
                continue
            snk_on = snk.enabled
            src_on = src.enabled
            if snk_on and not src_on:
                b = self._center(snk, area)
                if b:
                    direction = 3 if rd.is_mixer(snk.elem.port_category) else 1
                    painter.hidden_arrow(b, direction, card.src_level_db(src))
            if not snk_on and src_on:
                srcs_with_hidden_snk.add(src)

        for src in srcs_with_hidden_snk:
            a = self._center(src, area) if src in self.widgets else None
            if a:
                direction = 2 if rd.is_mixer(src.port_category) else 0
                painter.hidden_arrow(a, direction, card.src_level_db(src))

    def _stereo_positions(
        self, port: Port, target: Gtk.Widget
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """(left, right) centers of a linked pair, or None if mono."""
        left = port.left if port.is_linked else None
        w = self.widgets.get(left) if left else None
        if w is None or w.socket.get_parent() is None:
            return None
        pc = port.port_category
        x, y = _center(w.socket, target)
        l = self._stereo_offset(w.socket, pc, True, x, y)
        r = self._stereo_offset(w.socket, pc, False, x, y)
        if rd.is_mixer(pc):
            l, r = (l[0], l[1] + 1), (r[0], r[1] + 1)
        return l, r

    def _draw_drag_line(
        self, area: Gtk.DrawingArea, cr: cairo.Context[cairo.Surface], _width: int, _height: int
    ) -> None:
        if (
            self.drag_type == DRAG_NONE
            or (not self.src_drag and not self.snk_drag)
            or self.drag_x < 0
            or self.drag_y < 0
        ):
            return

        mouse = (0.0, 0.0)
        if not self.src_drag or not self.snk_drag:
            ok, p = self.routing_grid.compute_point(
                area, Graphene.Point.alloc().init(self.drag_x, self.drag_y)
            )
            if ok:
                mouse = (p.x, p.y)

        src_st = self._stereo_positions(self.src_drag, area) if self.src_drag else None
        snk_st = self._stereo_positions(self.snk_drag, area) if self.snk_drag else None

        a = mouse
        if self.src_drag and not src_st:
            a = self._center(self.src_drag, area) or mouse
        b = mouse
        if self.snk_drag and not snk_st:
            b = self._center(self.snk_drag, area) or mouse

        if src_st or snk_st:
            pairs = [
                (src_st[0] if src_st else a, snk_st[0] if snk_st else b),
                (src_st[1] if src_st else a, snk_st[1] if snk_st else b),
            ]
        else:
            pairs = [(a, b)]

        src_pc = self.src_drag.port_category if self.src_drag else PC.OFF
        snk_pc = self.snk_drag.elem.port_category if self.snk_drag else PC.OFF
        fg = area.get_color()

        for p1, p2 in pairs:
            if self.src_drag and self.snk_drag:
                cr.set_dash([])
                rd.Painter(cr).cable(rd.Cable(p1, src_pc, p2, snk_pc), (fg.red, fg.green, fg.blue))
            else:
                cr.set_dash(rd.DASH)
                cr.set_source_rgb(fg.red, fg.green, fg.blue)
                cr.set_line_width(2)
                cr.move_to(*p1)
                cr.line_to(*p2)
                cr.stroke()

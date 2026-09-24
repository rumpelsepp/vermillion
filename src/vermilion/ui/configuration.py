# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Settings sections: device name, front panel, autogain, I/O, monitor
groups."""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from vermilion.core.constants import HW, HW_TYPE_NAMES, PC
from vermilion.core.scope import Scope
from vermilion.ui.resources import blueprint
from vermilion.ui.widgets.elem import (
    ElemCheck,
    ElemComboRow,
    ElemEntry,
    ElemEntryRow,
    LinkToggle,
    VisibilityToggle,
)
from vermilion.ui.widgets.gain import GainControl

if TYPE_CHECKING:
    from vermilion.core.card import Card, Elem
    from vermilion.core.ports import Port, RoutingSnk, RoutingSrc
    from vermilion.ui.card_window import CardUI
    from vermilion.ui.settings import SettingsPage

IO_TAB_KEY = "configuration-io-tab"

SLEEP_PRESETS = [
    ("Off (never sleep)", 0),
    ("30 seconds", 30),
    ("1 minute", 60),
    ("5 minutes", 300),
    ("10 minutes", 600),
    ("30 minutes", 1800),
    ("1 hour", 3600),
    ("2 hours", 7200),
    ("4 hours", 14400),
    ("8 hours", 28800),
    ("24 hours", 86400),
]


def bold_label(text: str) -> Gtk.Label:
    label = Gtk.Label(halign=Gtk.Align.START)
    label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
    return label


def persist_view(stack: Adw.ViewStack, card: Card, key: str) -> None:
    """Restore the saved view of an Adw.ViewStack and save changes."""
    saved = card.prefs.view(key)
    if saved and stack.get_child_by_name(saved):
        stack.set_visible_child_name(saved)

    def switched(st: Adw.ViewStack, _pspec: GObject.ParamSpec | None) -> None:
        # during destruction the stack is already detached
        name = st.get_visible_child_name()
        if st.get_root() and name:
            card.prefs.set_view(key, name)

    stack.connect("notify::visible-child-name", switched)


class ShowAll:
    """The eye above a column of ports: open if any of them is shown;
    clicking hides them all, or shows them all if all are hidden."""

    def __init__(self, scope: Scope, button: Gtk.Button) -> None:
        self.scope = scope
        self.button = button
        self.elems: list[Elem] = []
        button.connect("clicked", self._clicked)

    def add(self, elem: Elem | None) -> None:
        if elem and elem not in self.elems:
            self.elems.append(elem)
            self.scope.watch(elem, lambda _e: self.refresh())

    def _any_shown(self) -> bool:
        return any(e.get_value() for e in self.elems)

    def refresh(self) -> None:
        shown = self._any_shown()
        self.button.set_icon_name("view-reveal-symbolic" if shown else "view-conceal-symbolic")
        self.button.set_tooltip_text("Hide all" if shown else "Show all")

    def _clicked(self, _button: Gtk.Button) -> None:
        value = 0 if self._any_shown() else 1
        for e in self.elems:
            e.set_value(value)


@Gtk.Template(string=blueprint("io_column"))
class IoColumn(Gtk.Box):
    __gtype_name__ = "IoColumn"

    show_all: Gtk.Button = Gtk.Template.Child()
    heading: Gtk.Label = Gtk.Template.Child()
    grid: Gtk.Grid = Gtk.Template.Child()

    def __init__(self, scope: Scope, title: str) -> None:
        super().__init__()
        self.heading.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        self.show_all_eye = ShowAll(scope, self.show_all)
        self.row = 0


class IoTab:
    """One I/O configuration tab (Analogue, S/PDIF, ADAT, PCM, DSP, Mixer)."""

    def __init__(self, config: ConfigurationSections, title: str, page_id: str) -> None:
        self.config = config
        self.scope = config.scope
        self.card = config.card
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=30)
        for side in ("top", "bottom", "start", "end"):
            getattr(self.box, f"set_margin_{side}")(20)
        self.columns: list[IoColumn] = []
        self.title = title
        self.page_id = page_id

    def column(self, title: str) -> IoColumn:
        col = IoColumn(self.scope, title)
        self.box.append(col)
        self.columns.append(col)
        return col

    def finish(self, stack: Adw.ViewStack) -> None:
        for col in self.columns:
            col.show_all_eye.refresh()
        stack.add_titled(self.box, self.page_id, self.title)

    # rows

    def _enable(self, col: IoColumn, elem: Elem | None) -> VisibilityToggle | None:
        if not elem:
            return None
        col.show_all_eye.add(elem)
        return VisibilityToggle(self.scope, elem)

    def _entry(self, elem: Elem | None, placeholder: str | None) -> ElemEntry | None:
        if not elem:
            return None
        e = ElemEntry(self.scope, elem, placeholder)
        e.set_hexpand(True)
        return e

    def _grey_when_hidden(self, widgets: Sequence[Gtk.Widget | None]) -> None:
        """Grey out a row while its eye is closed (not the eye itself)."""
        eye = next((w for w in widgets if isinstance(w, VisibilityToggle)), None)
        if not eye:
            return
        others = [w for w in widgets if w and w is not eye]

        def update(elem: Elem) -> None:
            for w in others:
                if elem.get_value():
                    w.remove_css_class("hidden-port")
                else:
                    w.add_css_class("hidden-port")

        self.scope.watch(eye.elem, update)
        update(eye.elem)

    def _attach_pair(
        self,
        col: IoColumn,
        link_elem: Elem,
        ch_widgets: Sequence[Sequence[Gtk.Widget | None]],
        pair_widgets: Sequence[Gtk.Widget | None],
        with_link: bool = True,
    ) -> None:
        """Two rows for a linkable pair; pair widgets span both rows and
        are shown instead of the per-channel widgets when linked."""
        grid = col.grid
        row = col.row
        offset = 1 if with_link else 0
        if with_link:
            grid.attach(LinkToggle(self.scope, link_elem), 0, row, 1, 2)

        for widgets in (*ch_widgets, pair_widgets):
            self._grey_when_hidden(widgets)
        for c, widgets in enumerate(ch_widgets):
            for i, w in enumerate(widgets):
                if w:
                    grid.attach(w, i + offset, row + c, 1, 1)
        for i, w in enumerate(pair_widgets):
            if w:
                w.set_valign(Gtk.Align.CENTER)
                grid.attach(w, i + offset, row, 1, 2)

        def update(_elem: Elem | None = None) -> None:
            linked = bool(link_elem.get_value())
            for widgets in ch_widgets:
                for w in widgets:
                    if w:
                        w.set_visible(not linked)
            for w in pair_widgets:
                if w:
                    w.set_visible(linked)

        self.scope.watch(link_elem, update)
        update()
        col.row += 2

    def _attach_single(
        self, col: IoColumn, widgets: Sequence[Gtk.Widget | None], first_col: int = 1
    ) -> None:
        self._grey_when_hidden(widgets)
        for i, w in enumerate(widgets):
            if w:
                col.grid.attach(w, first_col + i, col.row, 1, 1)
        col.row += 1

    def add_names(
        self, col: IoColumn, ports: Sequence[Port], pc: int, hw_type: int | None = None
    ) -> None:
        """Rows with visibility, generic name and custom name of the
        sources or sinks of a category; linked pairs in two rows."""
        for port in ports:
            if port.port_category != pc or not port.custom_name_elem:
                continue
            if pc == PC.HW and port.hw_type != hw_type:
                continue
            partner = port.partner
            if partner and not port.is_left:
                continue
            link = port.stereo_link_elem
            if partner and link:
                chans = [
                    [
                        self._enable(col, p.enable_elem),
                        Gtk.Label(label=p.generic_name, halign=Gtk.Align.START),
                        self._entry(p.custom_name_elem, p.device_name),
                    ]
                    for p in (port, partner)
                ]
                pair = [
                    self._enable(col, port.enable_elem),
                    Gtk.Label(label=port.generic_pair_name, halign=Gtk.Align.START),
                    self._entry(port.stereo_name_elem, port.device_pair_name),
                ]
                self._attach_pair(col, link, chans, pair)
            else:
                self._attach_single(
                    col,
                    [
                        self._enable(col, port.enable_elem),
                        Gtk.Label(label=port.generic_name, halign=Gtk.Align.START),
                        self._entry(port.custom_name_elem, port.device_name),
                    ],
                )

    def _mixer_label(self, snk: RoutingSnk) -> Gtk.Label:
        label = Gtk.Label(halign=Gtk.Align.START)
        self.config.label_updaters.append(lambda: label.set_text(snk.mixer_input_label))
        return label

    def _mixer_pair_label(self, snk_l: RoutingSnk, snk_r: RoutingSnk) -> Gtk.Label:
        label = Gtk.Label(halign=Gtk.Align.START)
        self.config.label_updaters.append(
            lambda: label.set_text(snk_l.mixer_input_pair_label(snk_r))
        )
        return label

    def add_snk_enables(
        self, col: IoColumn, pc: int, src_filter: Callable[[RoutingSrc | None], bool] | None = None
    ) -> None:
        """Enable check boxes (and labels) for mixer/DSP inputs."""
        card = self.card
        snks = [s for s in card.routing_snks if s.elem.port_category == pc and s.enable_elem]
        if src_filter:
            snks = [s for s in snks if src_filter(card.src(s.elem.get_value()))]

        skip = set()
        for i, snk in enumerate(snks):
            if snk in skip:
                continue

            # fixed mixer inputs: pair up inputs whose sources are a pair
            if pc == PC.MIX and card.has_fixed_mixer_inputs:
                src = card.src(snk.elem.get_value())
                src_link = src.stereo_link_elem if src and src.id else None
                if src and src_link and src.is_left:
                    src_partner = src.partner
                    nxt = snks[i + 1] if i + 1 < len(snks) else None
                    if src_partner and nxt and nxt.elem.get_value() == src_partner.id:
                        skip.add(nxt)
                        chans = [
                            [self._enable(col, s.enable_elem), self._mixer_label(s)]
                            for s in (snk, nxt)
                        ]
                        pair = [
                            self._enable(col, snk.enable_elem),
                            self._mixer_pair_label(snk, nxt),
                        ]
                        self._attach_pair(col, src_link, chans, pair, with_link=False)
                        continue
                self._attach_single(
                    col, [self._enable(col, snk.enable_elem), self._mixer_label(snk)], first_col=0
                )
                continue

            partner = snk.partner
            if partner and not snk.is_left:
                continue
            link = snk.stereo_link_elem
            if partner and link:
                chans = [
                    [self._enable(col, s.enable_elem), self._mixer_label(s)] for s in (snk, partner)
                ]
                pair = [self._enable(col, snk.enable_elem), self._mixer_pair_label(snk, partner)]
                self._attach_pair(col, link, chans, pair)
            else:
                self._attach_single(
                    col, [self._enable(col, snk.enable_elem), self._mixer_label(snk)], first_col=0
                )


class MonitorGroupsTab:
    """Main/Alt monitor group assignment, source and trim per output."""

    def __init__(self, config: ConfigurationSections, group: Adw.PreferencesGroup) -> None:
        self.config = config
        self.card = config.card
        self.scope: Scope | None = None
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"])
        group.add(self.content)
        self.grid: Gtk.Grid | None = None
        self.rebuild()
        config.scope.on_close(self._close)

    def _close(self) -> None:
        if self.scope:
            self.scope.close()

    def _group_elems(self, n: int) -> dict[str, Elem | None]:
        c = self.card
        return {
            key: c.elem(f"{g} Group Output {n} {suffix}")
            for key, g, suffix in (
                ("main", "Main", "Playback Switch"),
                ("alt", "Alt", "Playback Switch"),
                ("main_source", "Main", "Source Playback Enum"),
                ("alt_source", "Alt", "Source Playback Enum"),
                ("main_trim", "Main", "Trim Playback Volume"),
                ("alt_trim", "Alt", "Trim Playback Volume"),
            )
        }

    def rebuild(self) -> None:
        if self.scope:
            self.scope.close()
        if self.grid:
            self.content.remove(self.grid)
        scope = Scope()
        self.scope = scope
        self.grid = self._build(scope)
        self.content.append(self.grid)

    def _build(self, s: Scope) -> Gtk.Grid:
        card = self.card
        grid = Gtk.Grid(
            row_spacing=6,
            column_spacing=10,
            valign=Gtk.Align.START,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        first = self._group_elems(1)
        has_source = first["main_source"] is not None
        has_trim = first["main_trim"] is not None
        span = 1 + has_source + has_trim
        main_col = 2
        alt_col = main_col + span + 1

        for col, title in ((main_col, "Main"), (alt_col, "Alt")):
            grid.attach(bold_label(title), col, 0, span, 1)
            subs = ["Enable"] + (["Source"] if has_source else []) + (["Trim"] if has_trim else [])
            for i, t in enumerate(subs):
                label = Gtk.Label(label=t)
                label.add_css_class("dim-label")
                grid.attach(label, col + i, 1, 1, 1)

        row = 2
        n = 0
        while True:
            n += 1
            el = self._group_elems(n)
            if not el["main"] and not el["alt"]:
                break
            snk = card.analogue_output_snk(n)
            if snk and (
                not snk.should_display or not snk.enable_elem or not snk.enable_elem.get_value()
            ):
                continue
            linked = snk is not None and snk.is_linked

            label = Gtk.Label(halign=Gtk.Align.END, valign=Gtk.Align.CENTER)

            def update_label(
                _x: object = None, label: Gtk.Label = label, snk: RoutingSnk | None = snk
            ) -> None:
                if not snk:
                    label.set_text("")
                elif snk.is_linked:
                    label.set_text(snk.pair_display_name)
                else:
                    label.set_text(snk.display_name_formatted)

            update_label()
            if snk:
                s.connect(snk, "name-changed", update_label)
                pair_elem = snk.stereo_name_elem
                if pair_elem:
                    s.watch(pair_elem, update_label)
            grid.attach(label, 0, row, 1, 1)

            el_r: dict[str, Elem | None] = {}
            if snk and linked:
                partner = snk.partner
                if partner:
                    el_r = self._group_elems(partner.elem.lr_num)

            for group, col in (("main", main_col), ("alt", alt_col)):
                enable = el[group]
                if not enable:
                    continue
                deps: list[Gtk.Widget] = []
                c = col + 1
                source = el[f"{group}_source"]
                if has_source and source:
                    button = MonitorSourceButton(s, card, source, linked)
                    button.set_size_request(120, -1)
                    button.set_valign(Gtk.Align.CENTER)
                    grid.attach(button, c, row, 1, 1)
                    deps.append(button)
                if has_source:
                    c += 1
                trim = el[f"{group}_trim"]
                if has_trim and trim:
                    trims = [trim]
                    trim_r = el_r.get(f"{group}_trim") if linked else None
                    if trim_r:
                        trims.append(trim_r)
                    gain = GainControl(s, trims, zero_is_off=False, height=40)
                    gain.set_valign(Gtk.Align.CENTER)
                    grid.attach(gain, c, row, 1, 1)
                    deps.append(gain)

                grid.attach(ElemCheck(s, enable), col, row, 1, 1)

                def update_deps(e: Elem, deps: list[Gtk.Widget] = deps) -> None:
                    for w in deps:
                        w.set_sensitive(bool(e.get_value()))

                s.watch(enable, update_deps)
                update_deps(enable)

            row += 1

        for col in (main_col - 1, alt_col - 1):
            sep = Gtk.Separator(
                orientation=Gtk.Orientation.VERTICAL, margin_start=10, margin_end=10
            )
            grid.attach(sep, col, 0, 1, row)

        return grid


class MonitorSourceButton(Gtk.MenuButton):
    """Two-level source selection (port type submenus) for monitor groups."""

    def __init__(self, scope: Scope, card: Card, elem: Elem, stereo: bool) -> None:
        super().__init__()
        self.card = card
        self.elem = elem
        self.stereo = stereo
        self.add_css_class("drop-down")

        self._action = Gio.SimpleAction.new_stateful(
            "select", GLib.VariantType.new("i"), GLib.Variant("i", 0)
        )
        self._action.connect("activate", lambda _a, p: elem.set_value(p.get_int32()))
        group = Gio.SimpleActionGroup()
        group.add_action(self._action)
        self.insert_action_group("mg", group)

        scope.watch(elem, self._update)
        for src in card.routing_srcs:
            scope.connect(src, "name-changed", lambda _s: self._rebuild())
            if src.pair_name_elem:
                scope.watch(src.pair_name_elem, lambda _e: self._rebuild())
        self._rebuild()

    def _rebuild(self) -> None:
        menu = Gio.Menu()
        for group, items in self._source_items():
            if len(items) == 1:
                menu.append(items[0][1], f"mg.select({items[0][0]})")
                continue
            sub = Gio.Menu()
            for idx, label in items:
                sub.append(label, f"mg.select({idx})")
            menu.append_submenu(group, sub)
        self.set_menu_model(menu)
        self._update(self.elem)

    def _update(self, elem: Elem) -> None:
        self.set_sensitive(elem.writable())
        value = elem.get_value()
        self._action.set_state(GLib.Variant("i", value))
        self.set_label(self._item_label(value))

    # the sources to choose from

    def _src(self, enum_idx: int) -> RoutingSrc | None:
        card = self.card
        mg_map = card.monitor_group_src_map
        if not 0 <= enum_idx < len(mg_map):
            return None
        src_idx = mg_map[enum_idx]
        if src_idx <= 0 or src_idx >= len(card.routing_srcs):
            return None
        return card.routing_srcs[src_idx]

    def _item_label(self, enum_idx: int) -> str:
        src = self._src(enum_idx)
        if not src:
            return self.elem.item_name(enum_idx)
        if self.stereo and src.is_linked and src.is_left:
            return src.pair_display_name
        return src.display_name

    def _source_items(self) -> list[tuple[str, list[tuple[int, str]]]]:
        """Items grouped by port type: [(group, [(enum_idx, label)])].

        Stereo sinks show linked source pairs as one item; mono sinks don't
        offer linked sources at all. Hidden sources are left out.
        """
        groups: dict[str, list[tuple[int, str]]] = {}
        for i, alsa_name in enumerate(self.elem.items()):
            # "PCM 1" -> ("PCM", "1"); "Off" -> ("Off", None)
            head, sep, tail = alsa_name.rpartition(" ")
            group, suffix = (head, tail) if sep and head and tail.isalnum() else (alsa_name, None)
            src = self._src(i)
            if src:
                if not src.enabled:
                    continue
                if src.is_linked and (not self.stereo or not src.is_left):
                    continue
                suffix = self._item_label(i)
            groups.setdefault(group, []).append((i, suffix or alsa_name))
        return list(groups.items())


class ConfigurationSections:
    """Fills the configuration sections of the settings page."""

    def __init__(self, card_ui: CardUI, page: SettingsPage) -> None:
        self.card_ui = card_ui
        self.card = card_ui.card
        self.scope = card_ui.scope
        self.label_updaters: list[Callable[[], None]] = []
        self.monitor_groups = None

        self.device_group = page.device_group
        self.front_panel_group = page.front_panel_group
        self.autogain_group = page.autogain_group
        self._device_group()
        self._front_panel_group()
        self._autogain_group()
        self._io_group(page.io_group)
        if self.card.elem_by_prefix("Main Group Output"):
            self.monitor_groups = MonitorGroupsTab(self, page.monitor_group)
            page.monitor_group.set_visible(True)

        s = self.scope
        s.connect(self.card, "routing-changed", lambda _c: self.update_mixer_labels())
        s.connect(self.card, "stereo-changed", lambda _c: self.update_mixer_labels())
        for src in self.card.routing_srcs:
            s.connect(src, "name-changed", lambda _s: self.update_mixer_labels())
        self.update_mixer_labels()

    def update_mixer_labels(self) -> None:
        for fn in self.label_updaters:
            fn()

    def _device_group(self) -> bool:
        group = self.device_group
        elem = self.card.name_elem
        if elem:
            group.set_description(
                "The name will appear in the window title and can help you "
                "identify this device if you have multiple interfaces."
            )
            group.add(ElemEntryRow(self.scope, elem, "Name"))
        spdif = self.card.elem("S/PDIF Source Capture Enum")
        if spdif:
            group.add(
                ElemComboRow(
                    self.scope,
                    spdif,
                    "S/PDIF Source",
                    "None disables the S/PDIF input, Optical selects the optical "
                    "input and RCA the coaxial input.",
                )
            )
        group.set_visible(bool(elem or spdif))
        return group.get_visible()

    def _front_panel_group(self) -> bool:
        card = self.card
        group = self.front_panel_group
        brightness = card.elem("Front Panel Brightness")
        sleep = card.elem("Front Panel Sleep Time")
        if brightness:
            group.add(
                ElemComboRow(
                    self.scope,
                    brightness,
                    "Brightness",
                    "Brightness of the front panel LEDs.",
                )
            )
        if sleep:
            group.add(
                ElemComboRow(
                    self.scope,
                    sleep,
                    "Sleep Time",
                    "After this much inactivity (no front panel adjustments or "
                    "passing audio), the front panel LEDs turn off.",
                    presets=SLEEP_PRESETS,
                    custom_label=lambda v: f"Custom ({v} s)",
                )
            )
        group.set_visible(bool(brightness or sleep))
        return group.get_visible()

    def _autogain_group(self) -> bool:
        group = self.autogain_group
        targets = [
            (e, n) for n in ("Hot", "Mean", "Peak") if (e := self.card.elem(f"Autogain {n} Target"))
        ]
        group.set_visible(bool(targets))
        if not targets:
            return False
        group.set_description(
            "The target level Autogain aims for."
            if len(targets) == 1
            else "The target levels Autogain aims for."
        )
        box = Gtk.Box(spacing=24, css_classes=["card"])
        for elem, name in targets:
            col = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=6,
                margin_top=12,
                margin_bottom=12,
                margin_start=12,
            )
            col.append(Gtk.Label(label=name))
            col.append(GainControl(self.scope, elem, zero_is_off=False))
            box.append(col)
        group.add(box)
        return True

    def _has_io(
        self, pc: int, hw_type: int | None = None, srcs: bool = True, snks: bool = True
    ) -> bool:
        card = self.card
        if srcs and any(
            s.port_category == pc and (pc != PC.HW or s.hw_type == hw_type) and s.custom_name_elem
            for s in card.routing_srcs
        ):
            return True
        return snks and any(
            s.elem.port_category == pc
            and (pc != PC.HW or s.elem.hw_type == hw_type)
            and s.custom_name_elem
            for s in card.routing_snks
        )

    def _io_group(self, group: Adw.PreferencesGroup) -> None:
        card = self.card
        # sized to the visible tab (the tabs differ a lot in height)
        stack = Adw.ViewStack(vhomogeneous=False, enable_transitions=False)

        for hw_type, page_id in ((HW.ANALOGUE, "analogue"), (HW.SPDIF, "spdif"), (HW.ADAT, "adat")):
            has_in = self._has_io(PC.HW, hw_type, snks=False)
            has_out = self._has_io(PC.HW, hw_type, srcs=False)
            if not has_in and not has_out:
                continue
            tab = IoTab(self, HW_TYPE_NAMES[hw_type], page_id)
            if has_in:
                tab.add_names(tab.column("Inputs"), card.routing_srcs, PC.HW, hw_type)
            if has_out:
                tab.add_names(tab.column("Outputs"), card.routing_snks, PC.HW, hw_type)
            tab.finish(stack)

        # PCM: sources (outputs) on the left, sinks (inputs) on the right
        if self._has_io(PC.PCM):
            tab = IoTab(self, "PCM", "pcm")
            tab.add_names(tab.column("Outputs"), card.routing_srcs, PC.PCM)
            tab.add_names(tab.column("Inputs"), card.routing_snks, PC.PCM)
            tab.finish(stack)

        if self._has_io(PC.DSP):
            tab = IoTab(self, "DSP", "dsp")
            tab.add_snk_enables(tab.column("Inputs"), PC.DSP)
            tab.add_names(tab.column("Outputs"), card.routing_srcs, PC.DSP)
            tab.finish(stack)

        if self._has_io(PC.MIX):
            tab = IoTab(self, "Mixer", "mixer")
            if card.has_fixed_mixer_inputs:
                # one column per source type of the fixed inputs
                def of_type(pc: int, hw: int | None = None) -> Callable[[RoutingSrc | None], bool]:
                    return lambda src: (
                        src is not None
                        and src.port_category == pc
                        and (pc != PC.HW or src.hw_type == hw)
                    )

                types = [("PCM Outputs", of_type(PC.PCM))] + [
                    (f"{HW_TYPE_NAMES[h]} Inputs", of_type(PC.HW, h))
                    for h in (HW.ANALOGUE, HW.SPDIF, HW.ADAT)
                ]
                for title, flt in types:
                    if any(
                        flt(card.src(s.elem.get_value()))
                        for s in card.snks_of(PC.MIX)
                        if s.enable_elem
                    ):
                        tab.add_snk_enables(tab.column(title), PC.MIX, flt)
                if self._has_io(PC.MIX, snks=False):
                    tab.add_names(tab.column("Outputs"), card.routing_srcs, PC.MIX)
            else:
                tab.add_snk_enables(tab.column("Inputs"), PC.MIX)
                tab.add_names(tab.column("Outputs"), card.routing_srcs, PC.MIX)
            tab.finish(stack)

        if not stack.get_visible_child():
            return

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(Adw.InlineViewSwitcher(stack=stack, halign=Gtk.Align.START))
        card_box = Gtk.Box(css_classes=["card"])
        card_box.append(stack)
        box.append(card_box)
        group.add(box)
        group.set_visible(True)
        persist_view(stack, card, IO_TAB_KEY)

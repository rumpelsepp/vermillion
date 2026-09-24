# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""DSP window (Vocaster): pre-compressor filter, compressor, PEQ."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import Gio, GLib, GObject, Gtk

from vermilion.core import biquad
from vermilion.core.biquad import FilterType
from vermilion.core.features import dsp
from vermilion.ui.resources import blueprint
from vermilion.ui.widgets.elem import ElemToggle, LinkToggle
from vermilion.ui.widgets.graphs import CompressorCurve, FilterResponse

if TYPE_CHECKING:
    from vermilion.core.card import Elem
    from vermilion.core.ports import RoutingSnk, RoutingSrc
    from vermilion.ui.card_window import CardUI


@Gtk.Template(string=blueprint("dsp_section"))
class DspSection(Gtk.Box):
    __gtype_name__ = "DspSection"

    title: Gtk.Label = Gtk.Template.Child()
    presets: Gtk.MenuButton = Gtk.Template.Child()
    content: Gtk.Box = Gtk.Template.Child()

    def __init__(
        self, title: str, preset_names: list[str], apply_preset: Callable[[int], object]
    ) -> None:
        super().__init__()
        self.title.set_text(title)
        menu = Gio.Menu()
        for i, name in enumerate(preset_names):
            menu.append(name, f"dsp.preset({i})")
        self.presets.set_menu_model(menu)
        action = Gio.SimpleAction.new("preset", GLib.VariantType.new("i"))
        action.connect("activate", lambda _a, p: apply_preset(p.get_int32()))
        group = Gio.SimpleActionGroup()
        group.add_action(action)
        self.presets.insert_action_group("dsp", group)


def _parse(text: str, lo: float, hi: float) -> float | None:
    try:
        return min(max(float(text.split()[0]), lo), hi)
    except ValueError, IndexError:
        return None


class StageRow:
    """Controls for one filter stage in a grid row."""

    def __init__(
        self,
        stage: dsp.FilterStage,
        band: int,
        response: FilterResponse,
        grid: Gtk.Grid,
        row: int,
        label: str,
    ) -> None:
        self.stage = stage
        self.band = band
        self.response = response
        self.editing = False

        self.enable = Gtk.CheckButton(label=label, active=stage.enabled)
        self.type = Gtk.DropDown(model=Gtk.StringList.new(biquad.TYPE_NAMES))
        self.type.set_selected(int(stage.params.type))

        self.freq = self._entry(5)
        self.q = self._entry(4)
        self.gain = self._entry(5)
        self.freq_box = self._box(self.freq, None, "Hz")
        self.q_box = self._box(self.q, "Q", None)
        self.gain_box = self._box(self.gain, None, "dB")

        for col, w in enumerate((self.enable, self.type, self.freq_box, self.q_box, self.gain_box)):
            grid.attach(w, col, row, 1, 1)
            motion = Gtk.EventControllerMotion()
            motion.connect("enter", self._hover, True)
            motion.connect("leave", self._hover, False)
            w.add_controller(motion)

        self._h_enable = self.enable.connect("toggled", self._on_enable)
        self._h_type = self.type.connect("notify::selected", self._on_type)
        self._h_freq = self.freq.connect("changed", self._on_freq)
        self._h_q = self.q.connect("changed", self._on_q)
        self._h_gain = self.gain.connect("changed", self._on_gain)

        stage.connect("changed", self._on_stage_changed)
        self._format_entries()
        self._update_visibility()
        self._sync()

    @staticmethod
    def _entry(chars: int) -> Gtk.Entry:
        e = Gtk.Entry(max_width_chars=chars, width_chars=chars, max_length=chars)
        return e

    def _box(self, entry: Gtk.Entry, prefix: str | None, suffix: str | None) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        if prefix:
            box.append(Gtk.Label(label=prefix))
        box.append(entry)
        if suffix:
            box.append(Gtk.Label(label=suffix))

        focus = Gtk.EventControllerFocus()
        focus.connect("enter", self._focus_enter, entry)
        focus.connect("leave", self._focus_leave)
        entry.add_controller(focus)
        return box

    def _on_enable(self, button: Gtk.CheckButton) -> None:
        self.stage.set_enabled(button.get_active())
        self._sync()

    def _focus_enter(self, _ctrl: Gtk.EventController, entry: Gtk.Entry) -> None:
        self.editing = True

        def select_all() -> bool:
            entry.select_region(0, -1)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(select_all)

    def _focus_leave(self, _ctrl: Gtk.EventController) -> None:
        self.editing = False
        self._format_entries()

    def _hover(self, _ctrl: Gtk.EventController, *args: object) -> None:
        on = args[-1]
        self.response.set_highlight(self.band if on else -1)
        if on:
            self.enable.add_css_class("filter-stage-hover")
        else:
            self.enable.remove_css_class("filter-stage-hover")

    def _format_entries(self) -> None:
        p = self.stage.params
        for entry, handler, text in (
            (self.freq, self._h_freq, f"{p.freq:.0f}"),
            (self.q, self._h_q, f"{p.q:.2f}"),
            (self.gain, self._h_gain, f"{p.gain_db:+.1f}"),
        ):
            with entry.handler_block(handler):
                entry.set_text(text)

    def _update_visibility(self) -> None:
        t = self.stage.params.type
        self.gain_box.set_visible(biquad.uses_gain(t))
        self.freq_box.set_visible(t != FilterType.GAIN)
        self.q_box.set_visible(biquad.uses_q(t))

    def _sync(self) -> None:
        """Show the stage in the response graph."""
        self.response.set_filter(self.band, self.stage.params)
        self.response.set_band_enabled(self.band, self.stage.enabled)

    def _on_type(self, dropdown: Gtk.DropDown, _pspec: GObject.ParamSpec | None) -> None:
        self.stage.set_type(FilterType(dropdown.get_selected()))
        self._update_visibility()
        self._sync()

    def _on_freq(self, entry: Gtk.Entry) -> None:
        v = _parse(entry.get_text(), 20.0, 20000.0)
        if v is not None and v != self.stage.params.freq:
            self.stage.set_params(freq=v)
            self._sync()

    def _on_q(self, entry: Gtk.Entry) -> None:
        v = _parse(entry.get_text(), 0.1, 10.0)
        if v is not None and v != self.stage.params.q:
            self.stage.set_params(q=v)
            self._sync()

    def _on_gain(self, entry: Gtk.Entry) -> None:
        rng = self.response.db_range
        v = _parse(entry.get_text(), -rng, rng)
        if v is not None and v != self.stage.params.gain_db:
            self.stage.set_params(gain_db=v)
            self._sync()

    def set_from_graph(self, params: biquad.Params) -> None:
        self.stage.set_params(params.freq, params.q, params.gain_db)
        self._format_entries()

    def _on_stage_changed(self, stage: dsp.FilterStage, from_hardware: bool) -> None:
        with self.enable.handler_block(self._h_enable):
            self.enable.set_active(stage.enabled)
        with self.type.handler_block(self._h_type):
            self.type.set_selected(int(stage.params.type))
        if not self.editing:
            self._format_entries()
        self._update_visibility()
        self._sync()
        if from_hardware:
            self.response.auto_range()


@Gtk.Template(string=blueprint("dsp_panel"))
class DspPanel(Gtk.Box):
    __gtype_name__ = "DspPanel"

    channels: Gtk.Box = Gtk.Template.Child()

    def __init__(self, card_ui: CardUI) -> None:
        super().__init__()
        self.card = card = card_ui.card
        self.scope = card_ui.scope
        self.stages: list[dsp.FilterStage] = []
        # (curve, dsp snk, dsp src)
        self.curves: list[tuple[CompressorCurve, RoutingSnk | None, RoutingSrc | None]] = []

        assert card.dsp  # only created for cards with a DSP
        link = card.dsp.link_elem
        ch2_widgets = []

        for ch in card.dsp.channels:
            channel = ch.number
            widgets = self._add_channel(ch, link)
            if channel == 1 and link:
                self.channels.append(
                    LinkToggle(self.scope, link, "Link DSP channels as stereo pair")
                )
            if channel == 2:
                ch2_widgets = widgets

        if link and ch2_widgets:

            def update(_e: Elem | None = None) -> None:
                for w in ch2_widgets:
                    w.set_visible(not link.get_value())

            self.scope.watch(link, update)
            update()

    def close(self) -> None:
        for stage in self.stages:
            stage.close()
        self.stages = []

    def _header_name(self, src: RoutingSrc | None, link: Elem | None) -> str | None:
        if not src:
            return None
        if link and link.get_value():
            return src.pair_display_name
        return src.display_name

    def _add_channel(self, ch: dsp.DspChannel, link: Elem | None) -> list[Gtk.Widget]:
        channel = ch.number
        s = self.scope
        src = ch.src
        snk = ch.snk

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.channels.append(header_box)
        name = self._header_name(src, link) or f"DSP {channel}"
        enable = ch.elem("DSP Capture Switch")
        assert enable is not None  # channels are only added if they exist
        header = ElemToggle(s, enable, name)
        header_box.append(header)

        if src:

            def update_header(*_: object) -> None:
                n = self._header_name(src, link) or f"DSP {channel}"
                header.set_texts(n, n)

            s.connect(src, "name-changed", update_header)
            partner = src.partner
            if partner:
                s.connect(partner, "name-changed", update_header)
            for e in (src.stereo_name_elem, link):
                if e:
                    s.watch(e, update_header)

        sections = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, hexpand=True)
        self.channels.append(sections)

        responses = []
        curve = None

        # pre-compressor filter
        if ch.elem("Pre-Comp Filter Enable"):
            elems = ch.precomp_coeffs
            section = DspSection(
                "Pre-Compressor Filter",
                [p[0] for p in dsp.PRECOMP_PRESETS],
                lambda i: dsp.apply_coeff_preset(elems, dsp.PRECOMP_PRESETS[i][1:]),
            )
            responses.append(
                self._filter_section(
                    section, elems, "Pre-Comp", channel, "Stage", FilterType.HIGHPASS
                )
            )
            sections.append(section)
            sections.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # compressor
        if ch.elem("Compressor Enable"):
            section = DspSection(
                "Compressor",
                [p[0] for p in dsp.COMPRESSOR_PRESETS],
                lambda i: ch.apply_compressor_preset(dsp.COMPRESSOR_PRESETS[i]),
            )
            curve = CompressorCurve()
            section.content.append(curve)
            grid = Gtk.Grid(column_spacing=5, row_spacing=3)
            section.content.append(grid)
            row = 0
            for name, label, suffix, divisor, param in (
                ("Compressor Threshold", "Thresh", " dB", 1, "threshold"),
                ("Compressor Ratio", "Ratio", None, 2, "ratio"),
                ("Compressor Knee Width", "Knee", " dB", 1, "knee"),
                ("Compressor Attack", "Attack", " ms", 1, None),
                ("Compressor Release", "Release", " ms", 1, None),
                ("Compressor Makeup Gain", "Makeup", " dB", 1, "makeup"),
            ):
                elem = ch.elem(name)
                if not elem:
                    continue
                grid.attach(Gtk.Label(label=label, halign=Gtk.Align.END), 0, row, 1, 1)
                grid.attach(self._slider(elem, suffix, divisor, curve, param), 1, row, 1, 1)
                row += 1
            self.curves.append((curve, snk, src))
            sections.append(section)
            sections.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # parametric EQ
        if ch.elem("PEQ Filter Enable"):
            elems = ch.peq_coeffs
            section = DspSection(
                "Parametric EQ Filter",
                [p[0] for p in dsp.PEQ_PRESETS],
                lambda i: dsp.apply_coeff_preset(elems, dsp.PEQ_PRESETS[i][1:]),
            )
            section.set_hexpand(True)
            responses.append(
                self._filter_section(section, elems, "PEQ", channel, "Band", FilterType.PEAKING)
            )
            sections.append(section)

        def dsp_enabled(e: Elem) -> None:
            on = bool(e.get_value())
            for r in responses:
                r.set_dsp_enabled(on)
            if curve:
                curve.set_dsp_enabled(on)

        s.watch(enable, dsp_enabled)
        dsp_enabled(enable)

        return [header_box, sections]

    def _filter_section(
        self,
        section: DspSection,
        elems: list[Elem | None],
        filter_type: str,
        channel: int,
        label: str,
        default_type: FilterType,
    ) -> FilterResponse:
        response = FilterResponse(len(elems))
        section.content.append(response)
        grid = Gtk.Grid(column_spacing=10, row_spacing=3, hexpand=True)
        section.content.append(grid)

        rows = []
        for i, elem in enumerate(elems):
            if not elem:
                continue
            stage = dsp.FilterStage(self.card, elem, filter_type, channel, i + 1, default_type)
            self.stages.append(stage)
            rows.append(StageRow(stage, i, response, grid, i, f"{label} {i + 1}"))

        response.auto_range()

        def graph_changed(band: int, params: biquad.Params) -> None:
            for r in rows:
                if r.band == band:
                    r.set_from_graph(params)

        def highlight(band: int) -> None:
            for r in rows:
                if r.band == band:
                    r.enable.add_css_class("filter-stage-hover")
                else:
                    r.enable.remove_css_class("filter-stage-hover")

        response.connect("filter-changed", lambda _r, b, p: graph_changed(b, p))
        response.connect("highlight-changed", lambda _r, b: highlight(b))
        return response

    def _slider(
        self,
        elem: Elem,
        suffix: str | None,
        divisor: int,
        curve: CompressorCurve,
        param: str | None,
    ) -> Gtk.Scale:
        scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, elem.min_val, max(elem.max_val, elem.min_val + 1), 1
        )
        scale.set_size_request(150, -1)
        scale.set_hexpand(True)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)

        def format_value(_scale: Gtk.Scale, value: float) -> str:
            value = int(value)
            if divisor > 1:
                return (
                    f"{value // divisor}:1" if value % divisor == 0 else f"{value / divisor:.1f}:1"
                )
            return f"{value}{suffix or ''}"

        scale.set_format_value_func(format_value)

        handler = scale.connect("value-changed", lambda sc: elem.set_value(int(sc.get_value())))

        def update(e: Elem) -> None:
            value = e.get_value()
            with scale.handler_block(handler):
                scale.set_value(value)
            scale.set_sensitive(e.writable())
            if param:
                curve.set_param(param, value)

        self.scope.watch(elem, update)
        update(elem)
        return scale

    def update_levels(self) -> None:
        card = self.card
        for curve, snk, src in self.curves:
            in_db = card.level_db(snk.level_index) if snk and snk.level_index >= 0 else -80.0
            out_db = card.src_level_db(src) if src else -80.0
            curve.set_levels(in_db, out_db)

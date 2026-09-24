# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Controls page: global, input and output controls.

A preferences page like the settings: a row per global control, and a
row per analogue input and output, titled with the name of its port and
with the controls of the channel at its end. The controls of a kind are
in line across the rows (a size group per kind), so that the rows read
as a table.
"""

from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk

from vermilion.core.constants import HW, PC
from vermilion.core.features.sample_rate import format_sample_rate
from vermilion.core.util import get_num_from_string, get_two_nums_from_string
from vermilion.ui.presets import PresetsButton
from vermilion.ui.widgets.elem import (
    DualToggle,
    ElemComboRow,
    ElemDropDown,
    ElemLabel,
    ElemMenuButton,
    ElemStatus,
    ElemToggle,
    InputSelect,
    elem_switch_row,
)
from vermilion.ui.widgets.gain import GainControl

if TYPE_CHECKING:
    from vermilion.core.card import Card, Elem
    from vermilion.core.ports import Port, RoutingSnk, RoutingSrc
    from vermilion.core.scope import Scope
    from vermilion.ui.card_window import CardUI

LEVEL_DESCR = "Mic/Line or Instrument Level (Impedance)"
AIR_DESCR = "Enabling Air will transform your recordings and inspire you while making music."
PHANTOM_DESCR = (
    "Enabling 48V sends “Phantom Power” to the XLR microphone input. "
    "This is required for some microphones (such as condensor "
    "microphones), and damaging to some microphones (particularly "
    "vintage ribbon microphones)."
)
DIRECT_MONITOR_DESCR = (
    "Direct Monitor sends the analogue input signals to the analogue "
    "outputs for zero-latency monitoring."
)
TALKBACK_DESCR = (
    "Talkback lets you add another channel (usually the talkback mic) to "
    "a mix with a button push, usually to talk to musicians, and without "
    "using an additional mic channel."
)
SPEAKER_SWITCHING_DESCR = (
    "Speaker Switching lets you swap between two pairs of monitoring speakers very easily."
)
PAD_DESCR = (
    "Enabling Pad engages a 10dB attenuator in the channel, giving you more "
    "headroom for very hot signals."
)
MUTE_ICONS = ("*audio-volume-high-symbolic", "*audio-volume-muted-symbolic")

# the controls of an input row: (kind, element name part), in the order
# they are looked for
INPUT_CONTROLS = (
    ("link", "Link Capture Switch"),
    ("gain", "Gain Capture Volume"),
    ("autogain", "Autogain Capture Switch"),
    ("safe", "Safe Capture Switch"),
    ("inst", "Level Capture Enum"),
    ("inst", "Impedance Switch"),
    ("air", "Air Capture Switch"),
    ("air", "Air Capture Enum"),
    ("dsp", "DSP Capture Switch"),
    ("preset", "DSP Preset Capture Enum"),
    ("mute", "Mute Capture Switch"),
    ("pad", "Pad Capture Switch"),
    ("pad", "Pad Switch"),
    ("gain-switch", "Gain Switch"),
    ("phantom", "Phantom Power Capture Switch"),
)
# the order of the controls in the rows
INPUT_ORDER = ("select", *dict.fromkeys(kind for kind, _ in INPUT_CONTROLS))
# the fader last, so that it is in line in all rows (also in rows
# without some of the buttons)
OUTPUT_ORDER = ("group", "mute", "control", "gain")


# style of the sample rate: full features up to 48 kHz, some features
# unavailable above
RATE_STYLES = ((48000, "success"), (96000, "warning"), (None, "error"))
STATUS_STYLES = ("success", "warning", "error", "dim-label")


class StatusLabel(Gtk.Label):
    """A label coloured by a status (one of STATUS_STYLES, or None)."""

    def set_status(self, style: str | None) -> None:
        for c in STATUS_STYLES:
            self.remove_css_class(c)
        if style:
            self.add_css_class(style)


class SampleRateLabel(StatusLabel):
    """Indicator showing the current sample rate."""

    def __init__(self, scope: Scope, card: Card) -> None:
        super().__init__(label="N/A")
        self.add_css_class("heading")
        scope.connect(
            card, "sample-rate-changed", lambda _c, rate, current: self._update(rate, current)
        )
        mon = card.sample_rate
        if mon:
            self._update(max(mon.sample_rate, 0), mon.is_current)

    def _update(self, rate: int, is_current: bool) -> None:
        self.set_label(format_sample_rate(rate))
        if not rate or not is_current:
            self.set_status("dim-label")
            return
        self.set_status(
            next(style for limit, style in RATE_STYLES if limit is None or rate <= limit)
        )


def _row(
    title: str, *suffixes: Gtk.Widget, tooltip: str | None = None, subtitle: str = ""
) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    for widget in suffixes:
        widget.set_valign(Gtk.Align.CENTER)
        row.add_suffix(widget)
    if tooltip:
        row.set_tooltip_text(tooltip)
    return row


class _Group:
    """A preferences group which is only added to the page if it gets
    rows."""

    def __init__(self, title: str) -> None:
        self.group = Adw.PreferencesGroup(title=title)
        self.rows = 0

    def add(self, row: Adw.PreferencesRow) -> None:
        self.group.add(row)
        self.rows += 1

    def add_to(self, page: Adw.PreferencesPage) -> None:
        if self.rows:
            page.add(self.group)


class _ChannelRow(Adw.PreferencesRow):
    """A row like an Adw.ActionRow (the same style classes and spacing),
    whose controls can also take a second line."""

    def __init__(self, title: str, subtitle: str = "", tooltip: str | None = None) -> None:
        super().__init__(title=title, activatable=False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # the style of "row > box.header" applies to direct children of
        # the row only: its spacing is set here
        self.header = Gtk.Box(
            css_classes=["header"],
            spacing=6,
            margin_start=12,
            margin_end=12,
            height_request=50,
        )
        titles = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            css_classes=["title"],
            spacing=3,
            margin_top=6,
            margin_bottom=6,
            valign=Gtk.Align.CENTER,
            hexpand=True,
        )
        self.title_label = Gtk.Label(label=title, xalign=0, wrap=True, css_classes=["title"])
        self.subtitle_label = Gtk.Label(xalign=0, wrap=True, css_classes=["subtitle"])
        titles.append(self.title_label)
        titles.append(self.subtitle_label)
        self.set_subtitle(subtitle)
        self.suffixes = Gtk.Box(css_classes=["suffixes"], spacing=6, valign=Gtk.Align.CENTER)
        self.header.append(titles)
        self.header.append(self.suffixes)
        box.append(self.header)
        self.box = box
        self.set_child(box)
        if tooltip:
            self.set_tooltip_text(tooltip)

    def rename(self, title: str) -> None:
        self.set_title(title)
        self.title_label.set_label(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle_label.set_label(subtitle)
        self.subtitle_label.set_visible(bool(subtitle))

    def add_line(self, widget: Gtk.Widget) -> None:
        """A second line below the title, for the controls."""
        widget.set_margin_start(12)
        widget.set_margin_end(12)
        widget.set_margin_bottom(10)
        self.box.append(widget)


class _Table:
    """Channel rows whose controls line up: every row gets a slot for
    every kind of control any row has (empty where it has none). With
    many kinds, the controls other than the fader take a second line."""

    def __init__(self, order: tuple[str, ...]) -> None:
        self.order = order
        self.rows: list[tuple[_ChannelRow, dict[str, Gtk.Widget]]] = []
        self.sizes: dict[str, Gtk.SizeGroup] = {}

    def add(self, row: _ChannelRow, controls: dict[str, Gtk.Widget]) -> None:
        self.rows.append((row, controls))

    def finish(self, group: _Group) -> None:
        kinds = [k for k in self.order if any(k in controls for _, controls in self.rows)]
        two_lines = "gain" in kinds and len(kinds) > 4
        self.sizes = {k: Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL) for k in kinds}
        for row, controls in self.rows:
            line = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER, halign=Gtk.Align.END)
            for kind in kinds:
                widget = controls.get(kind) or Gtk.Box()
                widget.set_valign(Gtk.Align.CENTER)
                self.sizes[kind].add_widget(widget)
                if two_lines and kind == "gain":
                    row.suffixes.append(widget)
                else:
                    line.append(widget)
            if two_lines:
                row.add_line(line)
            else:
                row.suffixes.append(line)
            group.add(row)


class MainControls:
    """Builds the controls page."""

    def __init__(self, card_ui: CardUI, presets: bool = True) -> None:
        self.card_ui = card_ui
        self.card = card_ui.card
        self.scope = card_ui.scope
        self.presets = presets
        # kept for their size groups
        self.tables: list[_Table] = []
        # (GainControl, routing src) for input level display
        self.input_gains: list[tuple[GainControl, RoutingSrc | None]] = []
        # (GainControl, routing snk) for output level display
        self.output_gains: list[tuple[GainControl, RoutingSnk | None]] = []

    def _toggle(
        self, elem: Elem, off: str, on: str | None = None, tooltip: str | None = None
    ) -> ElemToggle:
        return ElemToggle(self.scope, elem, off, on, tooltip=tooltip)

    def _named_row(self, port: Port | None, fallback: str) -> _ChannelRow:
        """A row titled with the (custom) name of a port."""
        row = _ChannelRow(port.display_name if port else fallback)
        if port:
            self.scope.connect(port, "name-changed", lambda p: row.rename(p.display_name))
        return row

    # global controls

    def _global_controls(self, page: Adw.PreferencesPage) -> None:
        card = self.card
        s = self.scope
        group = _Group("Global")

        clock = card.elem_by_prefix("Clock Source") or card.elem_by_substr("Sync Clock Source")
        if clock:
            tip = (
                "Clock Source selects where the interface receives its digital clock "
                "from. If you aren’t using S/PDIF or ADAT inputs, set this to Internal."
            )
            row: Adw.PreferencesRow
            if clock.writable():
                row = ElemComboRow(s, clock, "Clock Source")
                row.set_tooltip_text(tip)
            else:
                row = _row("Clock Source", ElemLabel(s, clock), tooltip=tip)
            group.add(row)

        sync = card.elem("Sync Status") or card.elem("Sample Clock Sync Status")
        if sync:
            tip = (
                "Sync Status indicates if the interface is locked to a valid digital "
                "clock. If you aren’t using S/PDIF or ADAT inputs and the Sync Status "
                "is Unlocked, change the Clock Source to Internal."
                if card.elem_by_prefix("Clock Source")
                else "Sync Status indicates if the interface is locked to a valid "
                "digital clock. Since the Clock Source is fixed to internal on this "
                "interface, this should stay locked."
            )
            status = ElemStatus(s, sync, ("Unlocked", "error"), ("Locked", "success"))
            group.add(_row("Sync Status", status, tooltip=tip))

        power = card.elem("Power Status Card Enum")
        if power:
            group.add(
                _row(
                    "Power",
                    ElemLabel(s, power),
                    tooltip="Power indicates if the interface is being powered by the USB "
                    "bus, an external power supply, or if there is insufficient power "
                    "available and the interface has shut down.",
                )
            )

        # interfaces with a mixer, or with clock controls
        if self.presets or group.rows:
            group.add(
                _row(
                    "Sample Rate",
                    SampleRateLabel(s, card),
                    subtitle="Set by the application using the interface",
                    tooltip="The Sample Rate cannot be changed here because it is set by "
                    "the application which is using the interface, usually a sound server "
                    "like PulseAudio, JACK, or PipeWire. If this shows N/A, no application "
                    "is currently using the interface.\n\nNote that not all features are "
                    "available on all interfaces at sample rates above 48kHz. Please refer "
                    "to the user guide for your interface for more information.",
                )
            )

        elem = card.elem("Speaker Switching Playback Enum")
        if elem:
            dual = DualToggle(s, elem, None, ["Off", "On", "Main", "Alt"])
            group.add(_row("Speaker Switching", dual, tooltip=SPEAKER_SWITCHING_DESCR))

        enable = card.elem("Speaker Switching Playback Switch")
        alt = card.elem("Speaker Switching Alt Playback Switch")
        if enable and alt:
            group.add(
                _row(
                    "Speaker Switching",
                    self._toggle(enable, "Off", "On"),
                    self._toggle(alt, "Main", "Alt"),
                    tooltip=SPEAKER_SWITCHING_DESCR,
                )
            )

        # Gen 4: Main/Alt selector only (speaker switching is implicit)
        if card.elem_by_prefix("Main Group Output") and alt:
            toggle = self._toggle(alt, "Main", "Alt")

            def update_sensitivity(_elem: Elem | None = None, w: Gtk.Widget = toggle) -> None:
                w.set_sensitive(card.has_alt_group)

            update_sensitivity()
            for i in range(1, 9):
                e = card.elem(f"Alt Group Output {i} Playback Switch")
                if e:
                    s.watch(e, update_sensitivity)
            group.add(
                _row(
                    "Monitor Group",
                    toggle,
                    subtitle="Configure the groups in the settings",
                    tooltip="Monitor Group lets you swap between Main and Alt monitor groups.",
                )
            )

        elem = card.elem("Talkback Playback Enum")
        if elem:
            dual = DualToggle(s, elem, None, ["Disabled", "Enabled", "Off", "On"])
            group.add(_row("Talkback", dual, tooltip=TALKBACK_DESCR))

        enable = card.elem("Talkback Enable Playback Switch")
        talk = card.elem("Talk Playback Switch")
        if enable and talk:
            group.add(
                _row(
                    "Talkback",
                    self._toggle(enable, "Disabled", "Enabled"),
                    self._toggle(talk, "Talk", "Talk"),
                    tooltip=TALKBACK_DESCR,
                )
            )

        if self.presets and card.serial:
            group.add(
                _row(
                    "Presets",
                    PresetsButton(self.card_ui),
                    subtitle="Save and recall the whole configuration",
                )
            )

        group.add_to(page)

    # input controls

    def _input_control(self, kind: str, elem: Elem) -> Gtk.Widget | None:
        """The widget of an input control; None if it is in another row
        (the second input of a linked pair)."""
        s = self.scope
        if kind == "link":
            frm, _to = get_two_nums_from_string(elem.name)
            if frm % 2 == 0:
                return None
            return self._toggle(elem, "Link", tooltip="Link the pair as stereo")
        if kind == "gain":
            w = GainControl(s, elem, zero_is_off=False, show_level=True, horizontal=True)
            src = next(
                (
                    p
                    for p in self.card.routing_srcs
                    if p.port_category == PC.HW and p.port_num == elem.lr_num - 1
                ),
                None,
            )
            self.input_gains.append((w, src))
            return w
        if kind == "autogain":
            return self._toggle(
                elem,
                "Autogain",
                tooltip="Autogain will listen to the input signal for 10 seconds and "
                "automatically set the gain of the input channel to get the best "
                "signal level.",
            )
        if kind == "safe":
            return self._toggle(
                elem,
                "Safe",
                tooltip="Enabling Safe Mode prevents the input from clipping by "
                "automatically reducing the gain if the signal is too hot.",
            )
        if kind == "inst":
            return self._toggle(elem, "Inst", tooltip=LEVEL_DESCR)
        if kind == "air":
            if "Enum" in elem.name:
                return ElemMenuButton(s, elem, "Air", tooltip=AIR_DESCR)
            return self._toggle(elem, "Air", tooltip=AIR_DESCR)
        if kind == "dsp":
            return self._toggle(elem, "Enhance")
        if kind == "preset":
            return ElemDropDown(s, elem)
        if kind == "mute":
            return self._toggle(elem, "Mute")
        if kind == "pad":
            return self._toggle(elem, "Pad", tooltip=PAD_DESCR)
        if kind == "gain-switch":
            return self._toggle(
                elem,
                "Gain",
                tooltip="Enabling Gain switches from Low gain input (0dBFS = +16dBu)\n"
                "to High gain input (0dBFS = −10dBV, approx −6dBu).",
            )
        if kind == "phantom":
            frm, to = get_two_nums_from_string(elem.name)
            if to > frm:
                tip = f"{PHANTOM_DESCR}\n\nThis switch is shared by inputs {frm}–{to}."
                return self._toggle(elem, f"48V {frm}–{to}", tooltip=tip)
            return self._toggle(elem, "48V", tooltip=PHANTOM_DESCR)
        return None

    def _input_controls(self, page: Adw.PreferencesPage, input_count: int) -> None:
        card = self.card
        if not input_count:
            return
        group = _Group("Analogue Inputs")

        # 4th Gen Solo: mix of both inputs for PCM 1/2
        elem = card.elem("PCM Input Capture Switch")
        if elem:
            switch = elem_switch_row(
                self.scope, elem, "Input Mix", "Record Mix E/F instead of the inputs on PCM 1/2"
            )
            switch.set_tooltip_text(
                "Enabling Input Mix selects Mix E/F as the input source for the PCM 1/2 "
                "Inputs rather than the DSP 1/2 Inputs. This is useful to get a mono mix "
                "of both input channels."
            )
            group.add(switch)

        controls: dict[int, dict[str, Gtk.Widget]] = {i: {} for i in range(1, input_count + 1)}
        select = card.elem("Input Select Capture Enum")
        if select:
            for i, row_controls in controls.items():
                button = InputSelect(self.scope, select, i)
                button.set_label("Select")
                button.set_tooltip_text("Control this input with the front panel knob")
                row_controls["select"] = button

        status: dict[int, Elem] = {}
        for elem in card.elems:
            num = get_num_from_string(elem.name)
            if num not in controls:
                continue
            if "Autogain Status Capture Enum" in elem.name:
                status[num] = elem
                continue
            for kind, part in INPUT_CONTROLS:
                if part in elem.name:
                    if kind not in controls[num]:
                        widget = self._input_control(kind, elem)
                        if widget:
                            controls[num][kind] = widget
                    break

        table = _Table(INPUT_ORDER)
        for num, row_controls in controls.items():
            port = next(
                (
                    p
                    for p in card.routing_srcs
                    if p.port_category == PC.HW and p.hw_type == HW.ANALOGUE and p.lr_num == num
                ),
                None,
            )
            row = self._named_row(port, f"Input {num}")
            if num in status:
                self._autogain_status(row, status[num])
            table.add(row, row_controls)
        table.finish(group)
        self.tables.append(table)
        group.add_to(page)

    def _autogain_status(self, row: _ChannelRow, elem: Elem) -> None:
        """The last autogain result as the subtitle."""

        def update(elem: Elem) -> None:
            row.set_subtitle(f"Autogain: {elem.item_name(elem.get_value())}")

        self.scope.watch(elem, update)
        update(elem)

    # output controls

    def _monitor_group_label(self, lr_num: int) -> Gtk.Label | None:
        card = self.card
        snk = card.analogue_output_snk(lr_num)
        if not snk or not (snk.main_group_switch or snk.alt_group_switch):
            return None

        alt_switch = card.elem("Speaker Switching Alt Playback Switch")
        label = StatusLabel(css_classes=["caption"], width_chars=4)

        def update(_elem: Elem | None = None) -> None:
            in_main = bool(snk.main_group_switch and snk.main_group_switch.get_value())
            in_alt = bool(snk.alt_group_switch and snk.alt_group_switch.get_value())
            if not in_main and not in_alt:
                label.set_text("")
                return
            alt_active = bool(alt_switch and alt_switch.get_value())
            if in_main and not alt_active:
                label.set_text("Main")
                label.set_status("success")
            elif in_alt and alt_active:
                label.set_text("Alt")
                label.set_status("warning")
            else:
                label.set_text("Main" if in_main else "Alt")
                label.set_status("dim-label")

        for e in (snk.main_group_switch, snk.alt_group_switch, alt_switch):
            if e:
                self.scope.watch(e, update)
        update()
        return label

    def _output_volume_monitor_group(self, widget: Gtk.Widget, lr_num: int) -> None:
        """Volume is controlled by the monitor group if the output is in one."""
        snk = self.card.analogue_output_snk(lr_num)
        if not snk or not (snk.main_group_switch or snk.alt_group_switch):
            return

        def update(_elem: Elem | None = None) -> None:
            in_group = any(
                e and e.get_value() for e in (snk.main_group_switch, snk.alt_group_switch)
            )
            widget.set_sensitive(not in_group)

        for e in (snk.main_group_switch, snk.alt_group_switch):
            if e:
                self.scope.watch(e, update)
        update()

    def _output_port(self, lr_num: int) -> RoutingSnk | None:
        """The hardware output of the nth output controls (on the Gen 1, the
        last ones are S/PDIF outputs)."""
        card = self.card
        return card.analogue_output_snk(lr_num) or next(
            (
                r
                for r in card.routing_snks
                if r.elem.port_category == PC.HW and r.elem.lr_num == lr_num
            ),
            None,
        )

    def _knob_rows(self, table: _Table) -> None:
        """The volume knobs of the interface and their buttons."""
        card = self.card
        s = self.scope
        line_12_knob = bool(card.product and card.product.knob_controls_line_12)

        # Gen 1 master volume
        elem = card.elem("Master Playback Volume")
        if elem:
            w = GainControl(s, elem, zero_is_off=True, horizontal=True)
            table.add(_ChannelRow("Master", tooltip="Master Volume Control"), {"gain": w})

        knob = card.elem("Master HW Playback Volume")
        mute = card.elem("Mute Playback Switch")
        dim = card.elem("Dim Playback Switch")
        if knob or mute or dim:
            controls: dict[str, Gtk.Widget] = {}
            if knob:
                controls["gain"] = GainControl(
                    s, knob, zero_is_off=True, can_control=False, horizontal=True
                )
            if mute:
                controls["mute"] = self._toggle(
                    mute, *MUTE_ICONS, tooltip="Mute HW controlled outputs"
                )
            if dim:
                # in the column of the SW/HW buttons, which the knob row lacks
                controls["control"] = self._toggle(
                    dim,
                    "*audio-volume-medium-symbolic",
                    "*audio-volume-low-symbolic",
                    tooltip="Dim (lower volume) of HW controlled outputs",
                )
            if line_12_knob:
                row = _ChannelRow(
                    "Line 1–2 Knob",
                    tooltip="The setting of the master volume knob, which controls the "
                    "volume of the analogue line outputs 1 and 2.",
                )
            else:
                row = _ChannelRow(
                    "Volume Knob",
                    tooltip="The setting of the physical (hardware) volume knob, which "
                    "controls the volume of the analogue outputs which have been set to "
                    "“HW”.",
                )
            table.add(row, controls)

        elem = card.elem("Headphone Playback Volume")
        if elem:
            w = GainControl(s, elem, zero_is_off=True, can_control=False, horizontal=True)
            row = _ChannelRow(
                "Headphones Knob", tooltip="The setting of the headphone volume knob."
            )
            table.add(row, {"gain": w})

    def _output_controls(self, page: Adw.PreferencesPage, output_count: int) -> None:
        card = self.card
        s = self.scope
        group = _Group("Analogue Outputs")
        has_sw_hw = card.elem_by_substr("Volume Control Playback Enum") is not None

        # 4th Gen Solo/2i2 and 3rd Gen Solo/2i2
        elem = card.elem("Direct Monitor Playback Enum")
        if elem:
            combo = ElemComboRow(s, elem, "Direct Monitor")
            combo.set_tooltip_text(
                DIRECT_MONITOR_DESCR + " Mono sends both inputs to the left and right "
                "outputs. Stereo sends input 1 to the left, and input 2 to the right output."
            )
            group.add(combo)
        elem = card.elem("Direct Monitor Playback Switch")
        if elem:
            switch = elem_switch_row(s, elem, "Direct Monitor")
            switch.set_tooltip_text(DIRECT_MONITOR_DESCR)
            group.add(switch)

        table = _Table(OUTPUT_ORDER)
        self._knob_rows(table)

        outputs: dict[int, dict[str, Gtk.Widget]] = {i: {} for i in range(1, output_count + 1)}
        for elem in card.elems:
            name = elem.name
            lr = elem.lr_num
            if lr not in outputs or name == "Master HW Playback Volume":
                continue
            if not name.startswith(("Line", "Analogue", "Master")):
                continue
            if "Playback Volume" in name:
                w = GainControl(s, elem, zero_is_off=True, show_level=True, horizontal=True)
                self._output_volume_monitor_group(w, lr)
                outputs[lr]["gain"] = w
                self.output_gains.append((w, self._output_port(lr)))
            elif "Playback Switch" in name:
                outputs[lr]["mute"] = self._toggle(
                    elem,
                    *MUTE_ICONS,
                    tooltip="Mute (only available when under software control)"
                    if has_sw_hw
                    else "Mute",
                )
            elif "Volume Control Playback Enum" in name:
                outputs[lr]["control"] = self._toggle(
                    elem,
                    "SW",
                    "HW",
                    tooltip="Set software-controlled (SW) or hardware-controlled (HW) "
                    "volume for this analogue output.",
                )

        for lr, controls in outputs.items():
            label = self._monitor_group_label(lr)
            if label:
                controls["group"] = label
            if controls:
                table.add(self._named_row(self._output_port(lr), f"Output {lr}"), controls)

        # Vocaster: speaker and headphone mutes
        for elem in card.elems:
            name = elem.name
            if name == "Speaker Mute Playback Switch":
                mute = self._toggle(elem, *MUTE_ICONS, tooltip="Mute speaker output")
                table.add(_ChannelRow("Speaker"), {"mute": mute})
            elif "Headphones" in name and "Mute Playback Switch" in name:
                num = get_num_from_string(name)
                title = f"Headphones {num}" if num > 0 else "Headphones"
                mute = self._toggle(
                    elem,
                    "*audio-headphones-symbolic",
                    "*audio-headphones-symbolic",
                    tooltip=f"Mute {title.lower()} output",
                )
                table.add(_ChannelRow(title), {"mute": mute})

        table.finish(group)
        self.tables.append(table)
        group.add_to(page)

    def build(self) -> Adw.PreferencesPage:
        card = self.card
        page = Adw.PreferencesPage()

        input_count = card.max_elem_num("Line", "Capture Switch") or card.max_elem_num(
            "Input", "Switch"
        )
        output_count = (
            card.max_elem_num("Line", "Playback Volume")
            or card.max_elem_num("Master", "Playback Volume") * 2
            or card.max_elem_num("Analogue", "Playback Volume")
        )

        self._global_controls(page)
        self._input_controls(page, input_count)
        self._output_controls(page, output_count)
        return page

    # level display

    def update_levels(self) -> None:
        card = self.card
        for w, src in self.input_gains:
            if src:
                w.set_level(card.src_level_db(src))
        for w, snk in self.output_gains:
            if not snk or snk.level_index < 0:
                continue
            level: float | None = card.level_db(snk.level_index)
            # show -inf if muted by an inactive monitor group
            if snk.monitor_muted:
                level = None
            w.set_level(level)

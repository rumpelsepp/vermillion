# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The window of one card: all views in one window.

The views (controls, routing, mixer, ...) are pages of a Gtk.Stack
selected with a sidebar. Each page can be detached into a separate
window, e.g. to look at the mixer and the routing at the same time.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from vermilion.core.constants import Driver, UiUpdate
from vermilion.core.features.levels import LevelMonitor
from vermilion.core.scope import Scope
from vermilion.ui.dialogs import DeviceInfoDialog, ProgressDialog, confirm, show_about
from vermilion.ui.dsp import DspPanel
from vermilion.ui.file_dialogs import CONF, AlsaStateDialog, pick_file, simulate
from vermilion.ui.levels import LevelsPanel
from vermilion.ui.main_controls import MainControls
from vermilion.ui.mixer import MixerPanel
from vermilion.ui.panels import FcpPanel, FirmwareRequiredPanel, UnknownPanel
from vermilion.ui.resources import blueprint, builder
from vermilion.ui.routing import RoutingPanel
from vermilion.ui.settings import SettingsPage

if TYPE_CHECKING:
    from vermilion.core.card import Card
    from vermilion.core.device.maintenance import Maintenance, Reporter
    from vermilion.ui.app import Application
    from vermilion.ui.configuration import ConfigurationSections, MonitorGroupsTab

# page name -> title (in sidebar order)
PAGES = {
    "controls": "Controls",
    "routing": "Routing",
    "mixer": "Mixer",
    "levels": "Levels",
    "dsp": "DSP",
    "settings": "Settings",
}

PAGE_KEY = "page"

# page contents with their own scrolling
SELF_SCROLLING = (Adw.PreferencesPage, Adw.StatusPage)


def primary_menu() -> Gio.MenuModel:
    menu = builder("menus").get_object("primary_menu")
    assert isinstance(menu, Gio.MenuModel)
    return menu


class MainWindow(Adw.ApplicationWindow):
    """A main window: of an interface, or the one shown without one. They
    have the actions about, device information (about the interface of
    the window), ALSA state files and interface simulation."""

    __gtype_name__ = "MainWindow"

    def add_common_actions(self, card: Card | None = None) -> None:
        window = self
        for name, activate in (
            ("about", lambda: show_about(window)),
            ("device-info", lambda: DeviceInfoDialog(card).present(window)),
            ("sim", lambda: simulate(window)),
            ("alsa-state", lambda: AlsaStateDialog(card).present(window)),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_, fn=activate: fn())
            window.add_action(action)


@Gtk.Template(string=blueprint("no_card_window"))
class NoCardWindow(MainWindow):
    """Shown while no interface is found."""

    __gtype_name__ = "NoCardWindow"

    menu_button: Gtk.MenuButton = Gtk.Template.Child()

    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app)
        self.menu_button.set_menu_model(primary_menu())
        self.add_common_actions()


@Gtk.Template(string=blueprint("card_window"))
class CardWindow(MainWindow):
    __gtype_name__ = "CardWindow"

    mode: Gtk.Stack = Gtk.Template.Child()
    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    sidebar_page: Adw.NavigationPage = Gtk.Template.Child()
    sidebar_title: Gtk.Box = Gtk.Template.Child()
    sidebar_title_label: Gtk.Label = Gtk.Template.Child()
    sidebar_subtitle_label: Gtk.Label = Gtk.Template.Child()
    content_page: Adw.NavigationPage = Gtk.Template.Child()
    menu_button: Gtk.MenuButton = Gtk.Template.Child()
    stack: Gtk.Stack = Gtk.Template.Child()
    single_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    single_bin: Adw.Bin = Gtk.Template.Child()
    state_banner: Adw.Banner = Gtk.Template.Child()
    single_state_banner: Adw.Banner = Gtk.Template.Child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        menu = primary_menu()
        self.menu_button.set_menu_model(menu)
        self.single_menu_button.set_menu_model(menu)


@Gtk.Template(string=blueprint("detached_window"))
class DetachedWindow(Adw.Window):
    __gtype_name__ = "DetachedWindow"

    window_title: Adw.WindowTitle = Gtk.Template.Child()
    content_bin: Adw.Bin = Gtk.Template.Child()


@Gtk.Template(string=blueprint("detachable_page"))
class DetachablePage(Adw.Bin):
    """A page of the card window that can live in its own window."""

    __gtype_name__ = "DetachablePage"

    inner: Gtk.Stack = Gtk.Template.Child()
    content_bin: Adw.Bin = Gtk.Template.Child()

    def __init__(self, card_ui: CardUI, name: str, content: Gtk.Widget) -> None:
        super().__init__()
        self.card_ui = card_ui
        self.name = name
        self.window: DetachedWindow | None = None
        # pages like Adw.PreferencesPage scroll by themselves
        self.scrolls = not (
            isinstance(content, SELF_SCROLLING) or getattr(content, "self_scrolling", False)
        )
        self.widget: Gtk.Widget
        if self.scrolls:
            self.widget = Gtk.ScrolledWindow(
                propagate_natural_width=True,
                propagate_natural_height=True,
                child=content,
            )
        else:
            self.widget = content
        self.content_bin.set_child(self.widget)

    @property
    def detached(self) -> bool:
        return self.window is not None

    def visible(self) -> bool:
        """Is the page currently shown (in the stack or its own window)?"""
        if self.window:
            return self.window.get_visible()
        stack = self.card_ui.window.stack if self.card_ui.window else None
        return stack is not None and stack.get_visible_child() is self

    def detach(self) -> None:
        if self.window:
            self.window.present()
            return
        ui = self.card_ui
        self.content_bin.set_child(None)

        w = DetachedWindow(application=ui.app)
        if not self.scrolls:
            w.set_default_size(800, 600)
        w.content_bin.set_child(self.widget)
        # application accelerators (win.*) work through the card window
        w.insert_action_group("win", ui.window)
        w.connect("close-request", lambda _w: self.on_attach() or False)

        self.window = w
        self.inner.set_visible_child_name("detached")
        self.update_title()
        ui.card.prefs.set_view(f"detached-{self.name}", "true")
        ui.update_detach_action()
        w.present()

    @Gtk.Template.Callback()
    def on_attach(self, _button: Gtk.Button | None = None) -> None:
        if not self.window:
            return
        w = self.window
        self.window = None
        w.content_bin.set_child(None)
        w.destroy()
        self.content_bin.set_child(self.widget)
        self.inner.set_visible_child_name("content")
        if self.card_ui.window:
            self.card_ui.card.prefs.set_view(f"detached-{self.name}", "false")
            self.card_ui.update_detach_action()

    def update_title(self, base: str | None = None) -> None:
        if self.window:
            base = base or self.card_ui.card.window_title
            self.window.window_title.set_title(PAGES[self.name])
            self.window.window_title.set_subtitle(base)
            self.window.set_title(f"{base} – {PAGES[self.name]}")

    def destroy_window(self) -> None:
        if self.window:
            w = self.window
            self.window = None
            w.destroy()


class CardUI:
    def __init__(self, app: Application, card: Card) -> None:
        self.app = app
        self.card = card
        self.scope = Scope()
        # None once the window is closed
        self.window: CardWindow | None = None
        self.pages: dict[str, DetachablePage] = {}
        self.modal: ProgressDialog | None = None
        self._closed = False

        self.main_controls: MainControls | None = None
        self.routing: RoutingPanel | None = None
        self.mixer: MixerPanel | None = None
        self.levels: LevelsPanel | None = None
        self.dsp: DspPanel | None = None
        self.config: ConfigurationSections | None = None
        self.monitor_groups: MonitorGroupsTab | None = None

        self._build()

    @property
    def _win(self) -> CardWindow:
        """The window (while it is open)."""
        assert self.window is not None
        return self.window

    # configuration files and device operations

    def load_configuration(self) -> None:
        pick_file(self.window, "Load Configuration", CONF, False, self.card.config.load)

    def save_configuration(self) -> None:
        pick_file(self.window, "Save Configuration", CONF, True, self.card.config.save)

    def run_operation(self, title: str, message: str, start: Callable[[Reporter], object]) -> None:
        """A long-running device operation, with a progress dialog."""
        if not self.modal:
            self.modal = ProgressDialog(self, title, message, start)

    def confirm_reset_config(self, maintenance: Maintenance) -> None:
        if self.modal:
            return
        confirm(
            self.window,
            "Reset Configuration?",
            "The interface will be reset to its factory default settings. The "
            "firmware will be left unchanged.",
            "_Reset",
            lambda: self.run_operation(
                "Resetting Configuration",
                "Please do not disconnect the device.",
                maintenance.start_reset_config,
            ),
        )

    # construction

    def _build(self) -> None:
        card = self.card
        window = CardWindow(application=self.app)
        self.window = window
        window.connect("close-request", self._on_close_request)
        window.add_common_actions(card)

        single: Gtk.Widget | None = None
        if card.driver_type == Driver.FCP:
            single = FcpPanel()
        elif card.firmware_too_old:
            single = FirmwareRequiredPanel()
        elif card.elem_by_prefix("Matrix") or card.elem_by_prefix("Mixer"):
            self._build_mixer_iface(
                has_startup=not card.elem_by_prefix("Matrix")  # not on Gen 1
            )
        elif card.elem_by_prefix("Phantom"):
            self._add_page("controls", MainControls(self, presets=False).build())
            self._add_page(
                "settings",
                self._settings_page(
                    configuration=False,
                    display=False,
                ),
            )
        elif card.elem("MSD Mode Switch"):
            single = self._settings_page(configuration=False, display=False)
        else:
            single = UnknownPanel()

        if single:
            # nothing to choose from: no sidebar
            window.mode.set_visible_child_name("single")
            window.set_default_size(700, 550)
            window.single_bin.set_child(single)
        else:
            self._setup_page_action()

        if card.device:
            for name, fn in (("load", self.load_configuration), ("save", self.save_configuration)):
                action = Gio.SimpleAction.new(name, None)
                action.connect("activate", lambda *_, fn=fn: fn())
                window.add_action(action)

        name_elem = card.name_elem
        if name_elem:
            self.scope.connect(name_elem, "changed", lambda _e: self._update_titles())
        self._update_titles()

        if card.device_state:
            review = Gio.SimpleAction.new("review-state", None)
            review.connect("activate", lambda *_: self._review_state())
            window.add_action(review)
            self.scope.connect(card.device_state, "differs", lambda _s: self._show_state_banner())

        window.present()

        # restore detached pages after the window is shown
        for name, page in self.pages.items():
            if card.prefs.view(f"detached-{name}") == "true":
                page.detach()
        self.update_detach_action()

    # the settings of the interface differ from the recorded ones

    def _show_state_banner(self, show: bool = True) -> None:
        if not self.window or not self.card.device_state:
            return
        n = len(self.card.device_state.differences)
        title = f"{n} setting{'s' if n != 1 else ''} changed while Vermilion wasn’t running"
        for banner in (self.window.state_banner, self.window.single_state_banner):
            banner.set_title(title)
            banner.set_revealed(show)

    def _review_state(self) -> None:
        state = self.card.device_state
        if not state or not self.window:
            return
        names_ = sorted(state.differences)
        shown = "\n".join(f"• {n}" for n in names_[:8])
        if len(names_) > 8:
            shown += f"\n… and {len(names_) - 8} more"
        dialog = Adw.AlertDialog(
            heading="Restore Settings?",
            body=(
                "These settings of the interface differ from when Vermilion last saw it. "
                "Most likely the system’s ALSA state service (alsa-restore) wrote older "
                f"settings to it when it was connected.\n\n{shown}"
            ),
        )
        dialog.add_response("keep", "_Keep Current")
        dialog.add_response("restore", "_Restore")
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("restore")

        def response(_d: Adw.AlertDialog, answer: str) -> None:
            if answer == "restore":
                state.restore()
            elif answer == "keep":
                state.keep()
            else:
                return  # closed: decide later
            self._show_state_banner(False)

        dialog.connect("response", response)
        dialog.present(self.window)

    def _build_mixer_iface(self, has_startup: bool) -> None:

        card = self.card
        self.main_controls = MainControls(self)
        self._add_page("controls", self.main_controls.build())

        card.levels = LevelMonitor(card)

        if card.routing_srcs:
            self.routing = RoutingPanel(self)
            self._add_page("routing", self.routing)
            self.mixer = MixerPanel(self)
            self._add_page("mixer", self.mixer)

        if card.levels.available and card.has_levels:
            self.levels = LevelsPanel(self)
            self._add_page("levels", self.levels)

        if card.dsp:
            self.dsp = DspPanel(self)
            self._add_page("dsp", self.dsp)

        settings = self._settings_page(startup=has_startup)
        self.config = settings.config
        self.monitor_groups = self.config.monitor_groups if self.config else None
        self._add_page("settings", settings)

        self.scope.connect(card, "ui-update", lambda _c, f: self._on_ui_update(f))
        self.scope.connect(card, "levels-changed", lambda _c: self._on_levels())
        card.levels.start()

    def _settings_page(self, **sections: bool) -> SettingsPage:

        return SettingsPage(self, self.scope, **sections)

    def _add_page(self, name: str, content: Gtk.Widget) -> None:
        page = DetachablePage(self, name, content)
        self.pages[name] = page
        self._win.stack.add_titled(page, name, PAGES[name])

    def _setup_page_action(self) -> None:
        window = self._win
        saved = self.card.prefs.view(PAGE_KEY)
        first = saved if saved in self.pages else next(iter(self.pages))
        window.stack.set_visible_child_name(first)

        action = Gio.SimpleAction.new_stateful(
            "page", GLib.VariantType.new("s"), GLib.Variant("s", first)
        )
        action.connect("activate", self._on_page_action)
        window.add_action(action)
        self._page_action = action

        detach = Gio.SimpleAction.new("detach", None)
        detach.connect("activate", lambda *_: self._current_page().detach())
        window.add_action(detach)
        self._detach_action = detach

        window.stack.connect("notify::visible-child-name", self._on_page_changed)
        self._on_page_changed(window.stack, None)

    def _on_page_action(self, _action: Gio.SimpleAction, param: GLib.Variant) -> None:
        name = param.get_string()
        page = self.pages.get(name)
        if not page:
            return
        if page.window:
            page.window.present()
        else:
            self._win.stack.set_visible_child(page)
            self._win.split_view.set_show_content(True)

    def _current_page(self) -> DetachablePage:
        page = self._win.stack.get_visible_child()
        assert isinstance(page, DetachablePage)
        return page

    def update_detach_action(self) -> None:
        if self.pages and self.window:
            self._detach_action.set_enabled(not self._current_page().detached)

    def _on_page_changed(self, stack: Gtk.Stack, _pspec: GObject.ParamSpec | None) -> None:
        name = stack.get_visible_child_name()
        if name is None or name not in self.pages:
            return
        self._page_action.set_state(GLib.Variant("s", name))
        self._win.content_page.set_title(PAGES[name])
        self._win.split_view.set_show_content(True)
        self.update_detach_action()
        if _pspec is not None:
            self.card.prefs.set_view(PAGE_KEY, name)
        # show current levels immediately
        self._on_levels()

    def _update_titles(self) -> None:
        title = self.card.window_title
        if self.window:
            self.window.set_title(title)
            self.window.sidebar_page.set_title(title)
            main, sub = self.card.title_parts
            self.window.sidebar_title_label.set_label(main)
            self.window.sidebar_subtitle_label.set_label(sub)
            self.window.sidebar_subtitle_label.set_visible(bool(sub))
            self.window.sidebar_title.set_tooltip_text(title)
        for page in self.pages.values():
            page.update_title(title)

    # model notifications

    def _on_ui_update(self, flags: int) -> None:
        if flags & UiUpdate.MIXER_GRID:
            if self.mixer:
                self.mixer.update_labels()
                self.mixer.rebuild_grid()
            if self.config:
                self.config.update_mixer_labels()
        if flags & UiUpdate.MONITOR_GROUPS and self.monitor_groups:
            self.monitor_groups.rebuild()

    def rebuild_mixer_grid(self) -> None:
        if self.mixer:
            self.mixer.rebuild_grid()

    def _visible(self, name: str) -> bool:
        page = self.pages.get(name)
        return page is not None and page.visible()

    def _on_levels(self) -> None:
        if self.levels and self._visible("levels"):
            self.levels.update()
        if self.routing and self._visible("routing"):
            self.routing.queue_draw_lines()
        if self.mixer and self._visible("mixer"):
            self.mixer.update_levels()
        if self.main_controls and self._visible("controls"):
            self.main_controls.update_levels()
        if self.dsp and self._visible("dsp"):
            self.dsp.update_levels()

    # teardown

    def _cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.card.levels:
            self.card.levels.stop()
        self.scope.close()
        if self.dsp:
            self.dsp.close()
        for page in self.pages.values():
            page.destroy_window()

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        self._cleanup()
        self.window = None
        self.app.card_ui_closed(self)
        return False

    def suspend(self) -> None:
        """Card went away while restarting: wait for it to come back.

        The window stays open (with the progress dialog on top) until it
        is replaced by the window of the re-appeared card.
        """
        self._cleanup()
        if self.window:
            self.window.mode.set_visible_child_name("gone")

    def destroy(self) -> None:
        """Card went away: close all windows."""
        self._cleanup()
        if self.modal:
            self.modal.force_close()
            self.modal = None
        if self.window:
            w = self.window
            self.window = None
            w.destroy()

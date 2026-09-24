#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render the UI to PNG files without opening windows on the desktop.

Starts a private GTK Broadway display server (gtk4-broadwayd), runs the
application on it with simulated interfaces from .state files, shows
every page of every card window, and saves each one as a PNG. It also
detaches and re-attaches a page to exercise that code path.

Usage: tools/screenshot.py OUTPUT_DIR STATE_FILE...

Real interfaces are ignored and the configuration is written to a
temporary directory, so nothing on the system is changed.
"""

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

# imported for its side effect: it selects the versions of GTK and
# libadwaita (gi.require_version), which has to happen before they are
# imported from gi.repository below, hence also the isort split
import vermilion.ui  # noqa: F401

# isort: split
from gi.repository import Gio, GLib, Graphene, Gtk

from vermilion import log
from vermilion.core.manager import CardManager
from vermilion.ui.app import Application
from vermilion.ui.card_window import DetachablePage


def _free_display() -> int:
    for n in range(20, 100):
        if not Path("/run/user").joinpath(str(os.getuid()), f"broadway{n}.socket").exists():
            return n
    raise RuntimeError("no free broadway display")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    out_dir = Path(sys.argv[1]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    display = _free_display()
    server = subprocess.Popen(
        ["gtk4-broadwayd", f":{display}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)
    # keep the state, preferences and presets of the demos away from the user's
    home = Path(tempfile.mkdtemp(prefix="vermilion-"))
    try:
        env = dict(
            os.environ,
            GDK_BACKEND="broadway",
            BROADWAY_DISPLAY=f":{display}",
            XDG_STATE_HOME=str(home.joinpath("state")),
            XDG_CONFIG_HOME=str(home.joinpath("config")),
            XDG_DATA_HOME=str(home.joinpath("data")),
            ASG_SCREENSHOT_DIR=str(out_dir),
        )
        return subprocess.call([sys.executable, __file__, "--run", *sys.argv[2:]], env=env)
    finally:
        server.terminate()
        server.wait()


def run(state_files: list[str]) -> int:
    out_dir = Path(os.environ["ASG_SCREENSHOT_DIR"])
    errors: list[str] = []
    retries: dict[str, int] = {}
    steps: list[Callable[[], object]] = []

    def save(widget: Gtk.Widget, name: str) -> None:
        w, h = widget.get_width(), widget.get_height()
        snap = Gtk.Snapshot()
        Gtk.WidgetPaintable.new(widget).snapshot(snap, w, h)
        node = snap.to_node()
        if node is None or w <= 0 or h <= 0:
            # not rendered yet: try again after the next frame
            retries[name] = retries.get(name, 0) + 1
            if retries[name] < 10:
                widget.queue_draw()
                steps.insert(0, partial(save, widget, name))
            else:
                errors.append(f"could not render {name}")
            return
        native = widget.get_native()
        assert native is not None
        renderer = native.get_renderer()
        assert renderer is not None
        tex = renderer.render_texture(node, Graphene.Rect.alloc().init(0, 0, w, h))
        tex.save_to_png(str(out_dir.joinpath(f"{name}.png")))
        print(f"saved {name} ({w}x{h})")

    class SimulatedOnly(CardManager):
        """Ignores real interfaces."""

        def scan(self) -> None:
            pass

    log.setup()
    app = Application()
    # never hand the files to an instance running on the desktop (which
    # would open them there): this one runs on its own
    app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    app.manager = SimulatedOnly()

    def schedule() -> bool:
        # without a browser connected, broadway doesn't advance animations
        settings = Gtk.Settings.get_default()
        assert settings is not None
        settings.set_property("gtk-enable-animations", False)
        for card, ui in app.card_uis.items():
            # constant redraws for level updates would invalidate the
            # rendered frame; levels are static for simulated cards anyway
            if card.levels:
                card.levels.stop()
            base = card.name.replace(" ", "_")
            window = ui.window
            assert window is not None
            stack = window.stack
            names = list(ui.pages) or ["single"]
            for name in names:
                if name != "single":
                    steps.append(partial(stack.set_visible_child_name, name))
                steps.append(partial(save, window, f"{base}-{name}"))
            if "mixer" in ui.pages:
                page = ui.pages["mixer"]
                steps.append(page.detach)
                steps.append(partial(save_detached, page, f"{base}-detached"))
                steps.append(page.on_attach)
        steps.append(app.quit)

        def step() -> bool:
            if steps:
                steps.pop(0)()
                return GLib.SOURCE_CONTINUE
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(300, step)
        return GLib.SOURCE_REMOVE

    def save_detached(page: DetachablePage, name: str) -> None:
        assert page.window is not None
        save(page.window, name)

    GLib.timeout_add(1000, schedule)
    app.run([sys.argv[0], *state_files])

    for e in errors:
        print(e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--run":
        sys.exit(run(sys.argv[2:]))
    sys.exit(main())

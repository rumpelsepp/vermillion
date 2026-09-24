# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where files are kept, following the XDG Base Directory Specification.

GLib resolves the base directories ($XDG_STATE_HOME, $XDG_CONFIG_HOME,
$XDG_DATA_HOME and their defaults); below each the application has its
own directory:

- state: what the application restores on the next start, per device
  (<serial>.conf: the controls the driver lacks such as port names,
  stereo links, mute/solo; the window layout) and the recorded
  controls of the interface (<serial>-device.conf, see device.state)
- config: the preferences of a device (<serial>.conf)
- data: the presets saved by the user (presets/<serial>-<name>.conf)
"""

import logging
from pathlib import Path

from gi.repository import GLib

_log = logging.getLogger(__name__)

APP_DIR = "vermilion"


def state_dir() -> Path:
    return Path(GLib.get_user_state_dir()).joinpath(APP_DIR)


def config_dir() -> Path:
    return Path(GLib.get_user_config_dir()).joinpath(APP_DIR)


def presets_dir() -> Path:
    return Path(GLib.get_user_data_dir()).joinpath(APP_DIR, "presets")


def ensure_dir(path: Path) -> bool:
    """Create a directory (and its parents) if needed."""
    try:
        path.mkdir(mode=0o755, parents=True, exist_ok=True)
        return True
    except OSError as e:
        _log.warning(f"Failed to create directory {path}: {e}")
        return False

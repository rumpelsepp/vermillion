# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""vermilion-config: load a configuration (.conf) into a device."""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from vermilion import log
from vermilion.core import asound
from vermilion.core.asound import (
    ELEM_TYPE_BOOLEAN,
    ELEM_TYPE_BYTES,
    ELEM_TYPE_ENUMERATED,
    ELEM_TYPE_INTEGER,
    AlsaError,
    Ctl,
    ElemInfo,
)
from vermilion.core.constants import Driver
from vermilion.core.device import driver
from vermilion.core.products import is_focusrite_card_name
from vermilion.core.storage import state

# writable elements by name: (numid, info)
type Elems = dict[str, tuple[int, ElemInfo]]


def find_devices() -> list[tuple[str, str]]:
    """[(device, name)] of all Focusrite cards."""
    found = []
    for num in asound.card_numbers():
        device = f"hw:{num}"
        try:
            ctl = asound.Ctl(device)
        except AlsaError:
            continue
        try:
            name = ctl.card_name()
            if is_focusrite_card_name(name):
                found.append((device, name))
        except AlsaError:
            pass
        finally:
            ctl.close()
    return found


def list_devices() -> None:
    print("Available Focusrite devices:")
    devices = find_devices()
    for device, name in devices:
        print(f"  {device}  {name}")
    if not devices:
        print("  (none found)")


def scan_elements(ctl: Ctl) -> Elems:
    """Writable bool/enum/int/bytes elements by name."""
    elems: Elems = {}
    for numid in ctl.elem_numids():
        info = ctl.info(numid)
        if not info or not info["writable"]:
            continue
        if info["type"] not in (
            ELEM_TYPE_BOOLEAN,
            ELEM_TYPE_ENUMERATED,
            ELEM_TYPE_INTEGER,
            ELEM_TYPE_BYTES,
        ):
            continue
        elems.setdefault(info["name"], (numid, info))
    return elems


def _enum_index(ctl: Ctl, numid: int, info: ElemInfo, text: str) -> int:
    for i in range(info["items"]):
        if ctl.item_name(numid, i) == text:
            return i
    try:
        return int(text)
    except ValueError:
        return -1


def set_value(
    ctl: Ctl, numid: int, info: ElemInfo, text: str, verbose: bool, dry_run: bool
) -> bool:
    t, name = info["type"], info["name"]
    write: Callable[[], int]

    if t == ELEM_TYPE_BOOLEAN:
        v = 1 if text in ("true", "1") else 0
        if verbose:
            print(f"  {name} = {'true' if v else 'false'}")
        write = lambda: ctl.write_value(numid, t, 0, v)

    elif t == ELEM_TYPE_ENUMERATED:
        v = _enum_index(ctl, numid, info, text)
        if v < 0:
            print(f"Warning: Unknown enum value '{text}' for '{name}'", file=sys.stderr)
            return False
        if verbose:
            print(f"  {name} = {text}")
        write = lambda: ctl.write_value(numid, t, 0, v)

    elif t == ELEM_TYPE_INTEGER:
        values: list[int] = []
        for part in text.split(",")[: info["count"]]:
            try:
                values.append(int(part.strip()))
            except ValueError:
                break
        if verbose:
            print(f"  {name} = {text}")
        write = lambda: ctl.write_int_values(numid, values)

    else:  # bytes
        data = text.encode()[: info["count"]]
        data += b"\0" * (info["count"] - len(data))
        if verbose:
            print(f'  {name} = "{text}"')
        write = lambda: ctl.write_bytes(numid, data)

    if dry_run:
        return True
    err = write()
    if err < 0:
        print(f"Warning: Failed to set '{name}': {asound.strerror(err)}", file=sys.stderr)
        return False
    return True


def load_config(ctl: Ctl, elems: Elems, path: Path, verbose: bool, dry_run: bool) -> bool:
    kf = state.load_keyfile(path)
    if kf is None:
        print("Error loading config", file=sys.stderr)
        return False
    controls = state.keyfile_section(kf, state.SECTION_CONTROLS)
    if not controls:
        print("No [controls] section in config file", file=sys.stderr)
        return False

    set_count = skipped = 0
    # two passes: some elements may become writable after others are set
    for pass_num in range(2):
        for key, value in controls.items():
            entry = elems.get(key)
            if not entry:
                if pass_num == 1:
                    skipped += 1
                    if verbose:
                        print(f"Warning: Unknown control '{key}'", file=sys.stderr)
                continue
            numid, info = entry
            if set_value(ctl, numid, info, value, verbose and pass_num == 0, dry_run):
                set_count += 1

    msg = f"Applied {set_count} controls"
    if skipped:
        msg += f" ({skipped} skipped)"
    if dry_run:
        msg += " [dry-run]"
    print(msg)
    return True


def main(argv: Sequence[str] | None = None) -> int:
    log.setup()
    parser = argparse.ArgumentParser(
        prog="vermilion-config",
        description="Load configuration to Focusrite device",
    )
    parser.add_argument("-d", "--device", help="ALSA device (auto-detected if only one)")
    parser.add_argument(
        "-l", "--list", action="store_true", help="List available Focusrite devices"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show each control as it's set"
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true", help="Parse config but don't apply changes"
    )
    parser.add_argument("config", nargs="?", type=Path, help="configuration file (.conf)")
    args = parser.parse_args(argv)

    if args.list:
        list_devices()
        return 0

    config: Path | None = args.config
    if not config:
        parser.print_usage(sys.stderr)
        return 1

    device = args.device
    if not device:
        devices = find_devices()
        if not devices:
            print("Error: No Focusrite devices found", file=sys.stderr)
            return 1
        if len(devices) > 1:
            print("Error: Multiple Focusrite devices found, use -d to specify", file=sys.stderr)
            list_devices()
            return 1
        device = devices[0][0]

    if not config.exists():
        print(f"Error: Config file not found: {config}", file=sys.stderr)
        return 1
    if config.suffix != ".conf":
        print("Error: Config file must have .conf extension", file=sys.stderr)
        return 1

    if driver.detect(device) == Driver.FCP:
        print(f"Error: {device} uses the FCP driver, which is not supported yet", file=sys.stderr)
        return 1

    try:
        ctl = asound.Ctl(device)
    except AlsaError as e:
        print(f"Error opening device {device}: {e}", file=sys.stderr)
        return 1

    try:
        name = ctl.card_name()
        if not is_focusrite_card_name(name):
            print(f"Warning: {name} is not a recognised Focusrite device", file=sys.stderr)
        elif args.verbose:
            print(f"Device: {name}")

        elems = scan_elements(ctl)
        if not elems:
            print("Error: No writable controls found on device", file=sys.stderr)
            return 1
        if args.verbose:
            print(f"Found {len(elems)} writable controls")

        ok = load_config(ctl, elems, config, args.verbose, args.dry_run)
    finally:
        ctl.close()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

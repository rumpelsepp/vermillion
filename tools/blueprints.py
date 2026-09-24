#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compile the Blueprint files of the UI to GtkBuilder XML.

Each src/vermilion/ui/blueprints/<name>.blp is compiled to <name>.ui next
to it; the application loads the .ui files and doesn't need
blueprint-compiler. They are not checked in: the build backend (uv_build)
has no build step, so `just blueprints` creates them for development and
`just build` before building the package (which contains them).

Usage: tools/blueprints.py [--check]

With --check nothing is written; the exit status is 1 if a .ui file is
missing, stale or left over (a test runs this).
"""

import sys
from pathlib import Path

from blueprintcompiler import parser, tokenizer
from blueprintcompiler.outputs import XmlOutput

BLUEPRINTS = Path(__file__).parents[1].joinpath("src", "vermilion", "ui", "blueprints")


def compile_blueprint(path: Path) -> str:
    """The XML of a .blp file; raises SystemExit on errors."""
    source = path.read_text(encoding="utf-8")
    ast, errors, _ = parser.parse(tokenizer.tokenize(source))
    if errors or ast is None:
        if errors:
            errors.pretty_print(path.name, source, sys.stderr)
        raise SystemExit(f"Error compiling {path.name}")
    xml: str = XmlOutput().emit(ast)
    return xml


def main() -> int:
    check = sys.argv[1:] == ["--check"]
    if sys.argv[1:] not in ([], ["--check"]):
        print(__doc__)
        return 2

    problems = []
    sources = sorted(BLUEPRINTS.glob("*.blp"))
    for blp in sources:
        ui = blp.with_suffix(".ui")
        xml = compile_blueprint(blp)
        if ui.exists() and ui.read_text(encoding="utf-8") == xml:
            continue
        if check:
            problems.append(f"{ui.name} is {'stale' if ui.exists() else 'missing'}")
        else:
            ui.write_text(xml, encoding="utf-8")
            print(f"compiled {blp.name}")

    stems = {blp.stem for blp in sources}
    for ui in sorted(BLUEPRINTS.glob("*.ui")):
        if ui.stem in stems:
            continue
        if check:
            problems.append(f"{ui.name} has no .blp file")
        else:
            ui.unlink()
            print(f"removed {ui.name}")

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print("run `just blueprints`", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

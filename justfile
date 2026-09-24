# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

# `uv run` with the extra arguments of $UV_RUN_ARGS; the CI adds
# PyGObject and pycairo with them (built for its Python, instead of the
# ones of the distribution)
run := "uv run " + env("UV_RUN_ARGS", "")

# list the recipes
default:
    @just --list

# all linters and the tests
check: lint test

# all linters
lint: ruff mypy ty reuse

# ruff lints and formatting
ruff:
    {{ run }} ruff check
    {{ run }} ruff format --check

# mypy (strict)
mypy:
    {{ run }} mypy

# ty (with the extra arguments of $TY_ARGS)
ty:
    {{ run }} ty check {{ env("TY_ARGS", "") }}

# REUSE compliance (licence and copyright of every file)
reuse:
    {{ run }} reuse lint

# compile the Blueprint files to the .ui files the application loads
blueprints:
    {{ run }} python tools/blueprints.py

# the sdist and the wheel (in dist/), with the compiled Blueprint files
build: blueprints
    uv build

# tests
test *args: blueprints
    {{ run }} pytest {{ args }}

# format the code and apply the safe ruff fixes
fmt:
    {{ run }} ruff check --fix
    {{ run }} ruff format

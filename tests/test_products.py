# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The registry of the supported interfaces."""

import math
from pathlib import Path

import pytest

from vermilion.core.constants import HW, PC, SR
from vermilion.core.products import PRODUCTS, Product, by_demo, by_pid
from vermilion.core.products.base import ANALOGUE_IN, ANALOGUE_OUT

DEMO_DIR = Path(__file__).parents[1].joinpath("demo")


def test_unique() -> None:
    assert len({d.pid for d in PRODUCTS}) == len(PRODUCTS)
    assert len({d.name for d in PRODUCTS}) == len(PRODUCTS)
    assert len({type(d) for d in PRODUCTS}) == len(PRODUCTS)


@pytest.mark.parametrize("product", PRODUCTS, ids=lambda d: d.name)
def test_lookup(product: Product) -> None:
    assert by_pid(product.pid) is product
    if product.demo:
        assert by_demo(product.demo) is product
        assert DEMO_DIR.joinpath(f"{product.demo}.state").exists()


def test_every_demo_has_a_model() -> None:
    for f in DEMO_DIR.glob("*.state"):
        assert by_demo(f.stem), f


@pytest.mark.parametrize("product", PRODUCTS, ids=lambda d: d.name)
def test_pair_names_fit_port_names(product: Product) -> None:
    """A pair name for each pair of named ports, at most."""
    for key, pairs in product.pair_names.items():
        ports = product.port_names.get(key)
        if ports:
            assert len(pairs) <= math.ceil(len(ports) / 2), key


@pytest.mark.parametrize("product", PRODUCTS, ids=lambda d: d.name)
def test_digital_io_all_rates(product: Product) -> None:
    for io in product.digital_io.values():
        for sr in SR:
            assert all(n >= 0 for n in io.at(sr))


def test_names() -> None:
    gen3 = by_pid(0x8214)
    assert gen3 is not None and gen3.name == "Scarlett 18i8 3rd Gen"
    assert gen3.port_name(*ANALOGUE_IN, 0) == "Mic/Line/Inst 1"
    assert gen3.pair_name(*ANALOGUE_OUT, 2) == "Headphones 1"
    # the hardware type counts for hardware ports only
    assert gen3.port_name(PC.HW, HW.ADAT, False, 0) is None
    assert gen3.port_name(PC.HW, HW.ANALOGUE, False, 99) is None
    assert gen3.io_limits("Optical", SR.LOW) == (2, 2, 0, 0)
    assert gen3.io_limits("unknown", SR.LOW) is None


def test_clarett_plus_is_a_clarett_usb() -> None:
    usb, plus = by_pid(0x8207), by_pid(0x820B)
    assert usb is not None and plus is not None
    assert plus.family == "Clarett+" and usb.family == "Clarett USB"
    assert plus.port_names is usb.port_names
    assert plus.digital_io is usb.digital_io


def test_special_cases() -> None:
    assert [d.name for d in PRODUCTS if d.gen1] == [
        d.name for d in PRODUCTS if d.family == "1st Gen"
    ]
    assert all(d.knob_controls_line_12 == (d.family == "4th Gen") for d in PRODUCTS)


@pytest.mark.parametrize("product", PRODUCTS, ids=lambda d: d.name)
def test_digital_io_control(product: Product) -> None:
    """A table by mode needs the control that selects it."""
    modes = set(product.digital_io)
    if modes - {None}:
        assert product.digital_io_control
        assert None not in modes
    else:
        assert not product.digital_io_control
    if product.digital_io_help:
        assert product.digital_io_control and not product.digital_io_live

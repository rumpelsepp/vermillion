# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The supported interfaces: a class per product (in the module of its
family, see base.Product), and the list of them.

To add a product, subclass the class of its family, set its USB product
ID, name and whatever differs from the defaults, and add an instance to
PRODUCTS.
"""

from vermilion.core.products import (
    clarett,
    scarlett_gen1,
    scarlett_gen2,
    scarlett_gen3,
    scarlett_gen4,
    vocaster,
)
from vermilion.core.products.base import Product

FOCUSRITE_VID = 0x1235

# in the order of the "Supported Hardware" dialog
PRODUCTS: tuple[Product, ...] = (
    scarlett_gen1.Scarlett6i6Gen1(),
    scarlett_gen1.Scarlett8i6Gen1(),
    scarlett_gen1.Scarlett18i6Gen1(),
    scarlett_gen1.Scarlett18i8Gen1(),
    scarlett_gen1.Scarlett18i20Gen1(),
    scarlett_gen2.Scarlett6i6Gen2(),
    scarlett_gen2.Scarlett18i8Gen2(),
    scarlett_gen2.Scarlett18i20Gen2(),
    scarlett_gen3.ScarlettSoloGen3(),
    scarlett_gen3.Scarlett2i2Gen3(),
    scarlett_gen3.Scarlett4i4Gen3(),
    scarlett_gen3.Scarlett8i6Gen3(),
    scarlett_gen3.Scarlett18i8Gen3(),
    scarlett_gen3.Scarlett18i20Gen3(),
    scarlett_gen4.ScarlettSoloGen4(),
    scarlett_gen4.Scarlett2i2Gen4(),
    scarlett_gen4.Scarlett4i4Gen4(),
    scarlett_gen4.Scarlett16i16Gen4(),
    scarlett_gen4.Scarlett18i16Gen4(),
    scarlett_gen4.Scarlett18i20Gen4(),
    clarett.Clarett2PreUsb(),
    clarett.Clarett4PreUsb(),
    clarett.Clarett8PreUsb(),
    clarett.ClarettPlus2Pre(),
    clarett.ClarettPlus4Pre(),
    clarett.ClarettPlus8Pre(),
    vocaster.VocasterOne(),
    vocaster.VocasterTwo(),
)

_BY_PID = {d.pid: d for d in PRODUCTS}
_BY_DEMO = {d.demo: d for d in PRODUCTS if d.demo}

# ALSA card names of the supported interfaces start with one of these
CARD_NAME_PREFIXES = ("Scarlett", "Clarett", "Vocaster")


def by_pid(pid: int) -> Product | None:
    """The product with a USB product ID (None if not supported)."""
    return _BY_PID.get(pid)


def by_demo(name: str) -> Product | None:
    """The product a demo .state file (by its name) simulates."""
    return _BY_DEMO.get(name)


def is_focusrite_card_name(name: str) -> bool:
    return name.startswith(CARD_NAME_PREFIXES)


__all__ = ["FOCUSRITE_VID", "PRODUCTS", "Product", "by_demo", "by_pid", "is_focusrite_card_name"]

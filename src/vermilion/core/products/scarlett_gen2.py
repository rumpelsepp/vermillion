# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scarlett 2nd Gen (Scarlett2 driver)."""

from vermilion.core.products.base import (
    ANALOGUE_IN,
    ANALOGUE_OUT,
    INST_12_LINE_34,
    INST_12_MIC_34_LINE_5678,
    INST_12_MIC_345678,
    DigitalIo,
    Product,
    frozen,
)


class ScarlettGen2(Product):
    family = "2nd Gen"


class Scarlett6i6Gen2(ScarlettGen2):
    pid = 0x8203
    name = "Scarlett 6i6 2nd Gen"
    demo = "Scarlett Gen 2 6i6"
    port_names = frozen(
        {
            ANALOGUE_IN: ("Mic/Line/Inst 1", "Mic/Line/Inst 2", "Line 3", "Line 4"),
            ANALOGUE_OUT: (
                "Line 1/Headphones 1 (L)",
                "Line 2/Headphones 1 (R)",
                "Line 3/Headphones 2 (L)",
                "Line 4/Headphones 2 (R)",
            ),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_IN: INST_12_LINE_34,
            ANALOGUE_OUT: ("Line 1–2/Headphones 1", "Line 3–4/Headphones 2"),
        }
    )


class Scarlett18i8Gen2(ScarlettGen2):
    pid = 0x8204
    name = "Scarlett 18i8 2nd Gen"
    demo = "Scarlett Gen 2 18i8"
    port_names = frozen(
        {
            ANALOGUE_IN: (
                "Mic/Line/Inst 1",
                "Mic/Line/Inst 2",
                "Mic/Line 3",
                "Mic/Line 4",
                "Line 5",
                "Line 6",
                "Line 7",
                "Line 8",
            ),
            ANALOGUE_OUT: (
                "Line 1",
                "Line 2",
                "Headphones 1 (L)",
                "Headphones 1 (R)",
                "Headphones 2 (L)",
                "Headphones 2 (R)",
            ),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_IN: INST_12_MIC_34_LINE_5678,
            ANALOGUE_OUT: ("Line 1–2", "Headphones 1", "Headphones 2"),
        }
    )
    digital_io = frozen(
        {
            None: DigitalIo((2, 2, 2), (2, 2, 2), (8, 4, 0), (0, 0, 0)),
        }
    )


class Scarlett18i20Gen2(ScarlettGen2):
    pid = 0x8201
    name = "Scarlett 18i20 2nd Gen"
    demo = "Scarlett Gen 2 18i20"
    port_names = frozen(
        {
            ANALOGUE_IN: (
                "Mic/Line/Inst 1",
                "Mic/Line/Inst 2",
                "Mic/Line 3",
                "Mic/Line 4",
                "Mic/Line 5",
                "Mic/Line 6",
                "Mic/Line 7",
                "Mic/Line 8",
            ),
            ANALOGUE_OUT: (
                "Line 1 (Main L)",
                "Line 2 (Main R)",
                "Line 3 (Alt L)",
                "Line 4 (Alt R)",
                "Line 5",
                "Line 6",
                "Line 7/Headphones 1 (L)",
                "Line 8/Headphones 1 (R)",
                "Line 9/Headphones 2 (L)",
                "Line 10/Headphones 2 (R)",
            ),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_IN: INST_12_MIC_345678,
            ANALOGUE_OUT: (
                "Main",
                "Alt",
                "Line 5–6",
                "Line 7–8/Headphones 1",
                "Line 9–10/Headphones 2",
            ),
        }
    )
    digital_io = frozen(
        {
            None: DigitalIo((2, 2, 2), (2, 2, 2), (8, 4, 0), (8, 4, 0)),
        }
    )

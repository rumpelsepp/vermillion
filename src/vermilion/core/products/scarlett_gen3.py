# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scarlett 3rd Gen (Scarlett2 driver)."""

from vermilion.core.products.base import (
    ANALOGUE_IN,
    ANALOGUE_OUT,
    INST_12_LINE_34,
    INST_12_LINE_3456,
    INST_12_MIC_34_LINE_5678,
    INST_12_MIC_345678,
    DigitalIo,
    Product,
    frozen,
)


class ScarlettGen3(Product):
    family = "3rd Gen"


class ScarlettSoloGen3(ScarlettGen3):
    pid = 0x8211
    name = "Scarlett Solo 3rd Gen"
    demo = "Scarlett Gen 3 Solo"


class Scarlett2i2Gen3(ScarlettGen3):
    pid = 0x8210
    name = "Scarlett 2i2 3rd Gen"
    demo = "Scarlett Gen 3 2i2"


class Scarlett4i4Gen3(ScarlettGen3):
    pid = 0x8212
    name = "Scarlett 4i4 3rd Gen"
    demo = "Scarlett Gen 3 4i4"
    port_names = frozen(
        {
            ANALOGUE_IN: ("Mic/Line/Inst 1", "Mic/Line/Inst 2", "Line 3", "Line 4"),
            ANALOGUE_OUT: ("Line 1", "Line 2", "Line 3/Headphones (L)", "Line 4/Headphones (R)"),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_IN: INST_12_LINE_34,
            ANALOGUE_OUT: ("Line 1–2", "Line 3–4/Headphones"),
        }
    )


class Scarlett8i6Gen3(ScarlettGen3):
    pid = 0x8213
    name = "Scarlett 8i6 3rd Gen"
    demo = "Scarlett Gen 3 8i6"
    port_names = frozen(
        {
            ANALOGUE_IN: (
                "Mic/Line/Inst 1",
                "Mic/Line/Inst 2",
                "Line 3",
                "Line 4",
                "Line 5",
                "Line 6",
            ),
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
            ANALOGUE_IN: INST_12_LINE_3456,
            ANALOGUE_OUT: ("Line 1–2/Headphones 1", "Line 3–4/Headphones 2"),
        }
    )


class Scarlett18i8Gen3(ScarlettGen3):
    pid = 0x8214
    name = "Scarlett 18i8 3rd Gen"
    demo = "Scarlett Gen 3 18i8"
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
                "Line 3",
                "Line 4",
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
            ANALOGUE_OUT: ("Line 1–2", "Line 3–4", "Headphones 1", "Headphones 2"),
        }
    )
    digital_io_control = "S/PDIF Mode"
    digital_io_help = (
        "S/PDIF Mode selects whether the interface receives S/PDIF input from the coaxial "
        "(RCA) connector or the optical (TOSLINK) connector. This requires a reboot to take "
        "effect."
    )
    digital_io = frozen(
        {
            "RCA": DigitalIo((2, 2, 2), (2, 2, 2), (8, 4, 0), (0, 0, 0)),
            "Optical": DigitalIo((2, 2, 2), (2, 2, 2), (0, 0, 0), (0, 0, 0)),
        }
    )


class Scarlett18i20Gen3(ScarlettGen3):
    pid = 0x8215
    name = "Scarlett 18i20 3rd Gen"
    demo = "Scarlett Gen 3 18i20"
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
                "Talkback Mic",
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
    digital_io_control = "Digital I/O Mode"
    digital_io_help = (
        "Digital I/O Mode selects whether the interface receives S/PDIF input from the "
        "coaxial (RCA) connector, the optical connector, or whether Dual ADAT mode is "
        "enabled. This requires a reboot to take effect."
    )
    digital_io = frozen(
        {
            "S/PDIF RCA": DigitalIo((2, 2, 2), (2, 2, 2), (8, 4, 0), (16, 4, 0)),
            "S/PDIF Optical": DigitalIo((2, 2, 0), (4, 4, 2), (8, 4, 0), (8, 4, 0)),
            "Dual ADAT": DigitalIo((0, 0, 0), (2, 2, 2), (8, 8, 0), (16, 8, 0)),
        }
    )

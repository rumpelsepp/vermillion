# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Clarett USB and Clarett+ (Scarlett2 driver); a Clarett+ is a Clarett USB
with a new product ID."""

from vermilion.core.products.base import (
    ANALOGUE_IN,
    ANALOGUE_OUT,
    INST_12,
    INST_12_MIC_34_LINE_5678,
    INST_12_MIC_345678,
    DigitalIo,
    Product,
    frozen,
)


class ClarettUsb(Product):
    family = "Clarett USB"


class Clarett2PreUsb(ClarettUsb):
    pid = 0x8206
    name = "Clarett 2Pre USB"
    port_names = frozen(
        {
            ANALOGUE_IN: ("Mic/Line/Inst 1", "Mic/Line/Inst 2"),
            ANALOGUE_OUT: ("Line 1", "Line 2", "Line 3/Headphones (L)", "Line 4/Headphones (R)"),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_IN: INST_12,
            ANALOGUE_OUT: ("Line 1–2", "Line 3–4/Headphones"),
        }
    )
    digital_io = frozen(
        {
            None: DigitalIo((2, 2, 0), (2, 2, 2), (8, 4, 0), (0, 0, 0)),
        }
    )


class Clarett4PreUsb(ClarettUsb):
    pid = 0x8207
    name = "Clarett 4Pre USB"
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
                "Line 3/Headphones 1 (L)",
                "Line 4/Headphones 1 (R)",
                "Headphones 2 (L)",
                "Headphones 2 (R)",
            ),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_IN: INST_12_MIC_34_LINE_5678,
            ANALOGUE_OUT: ("Line 1–2", "Line 3–4/Headphones 1", "Headphones 2"),
        }
    )
    digital_io_control = "S/PDIF Source"
    digital_io_live = True
    digital_io = frozen(
        {
            "None": DigitalIo((0, 0, 0), (2, 2, 2), (8, 4, 0), (8, 4, 0)),
            "Optical": DigitalIo((2, 2, 2), (2, 2, 2), (0, 0, 0), (8, 4, 0)),
            "RCA": DigitalIo((2, 2, 2), (2, 2, 2), (8, 4, 0), (8, 4, 0)),
        }
    )


class Clarett8PreUsb(ClarettUsb):
    pid = 0x8208
    name = "Clarett 8Pre USB"
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
                "Line 1",
                "Line 2",
                "Line 3",
                "Line 4",
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
                "Line 1–2",
                "Line 3–4",
                "Line 5–6",
                "Line 7–8/Headphones 1",
                "Line 9–10/Headphones 2",
            ),
        }
    )
    digital_io_control = "S/PDIF Source"
    digital_io_live = True
    digital_io = frozen(
        {
            "None": DigitalIo((0, 0, 0), (2, 2, 2), (8, 4, 0), (8, 4, 0)),
            "Optical": DigitalIo((2, 2, 2), (2, 2, 2), (0, 0, 0), (8, 4, 0)),
            "RCA": DigitalIo((2, 2, 2), (2, 2, 2), (8, 4, 0), (8, 4, 0)),
        }
    )


class ClarettPlus2Pre(Clarett2PreUsb):
    """The Clarett 2Pre USB with a new product ID."""

    pid = 0x820A
    name = "Clarett+ 2Pre"
    family = "Clarett+"
    demo = "Clarett Plus 2Pre"


class ClarettPlus4Pre(Clarett4PreUsb):
    """The Clarett 4Pre USB with a new product ID."""

    pid = 0x820B
    name = "Clarett+ 4Pre"
    family = "Clarett+"
    demo = "Clarett Plus 4Pre"


class ClarettPlus8Pre(Clarett8PreUsb):
    """The Clarett 8Pre USB with a new product ID."""

    pid = 0x820C
    name = "Clarett+ 8Pre"
    family = "Clarett+"
    demo = "Clarett Plus 8Pre"

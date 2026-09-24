# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scarlett 4th Gen: Scarlett2 driver for the small models, FCP for the
large ones (not supported yet, see device.driver; their demos can be
simulated)."""

from vermilion.core.products.base import (
    ANALOGUE_IN,
    ANALOGUE_OUT,
    INST_12,
    INST_12_LINE_34,
    INST_12_LINE_3456,
    INST_12_MIC_34_LINE_5678,
    INST_12_MIC_345678,
    DigitalIo,
    Product,
    frozen,
)


class ScarlettGen4(Product):
    family = "4th Gen"
    knob_controls_line_12 = True


class ScarlettSoloGen4(ScarlettGen4):
    pid = 0x8218
    name = "Scarlett Solo 4th Gen"
    demo = "Scarlett Gen 4 Solo"
    port_names = frozen(
        {
            ANALOGUE_IN: ("Line/Inst", "Mic"),
            ANALOGUE_OUT: ("Line 1/Headphones (L)", "Line 2/Headphones (R)"),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_OUT: ("Line 1–2/Headphones",),
        }
    )


class Scarlett2i2Gen4(ScarlettGen4):
    pid = 0x8219
    name = "Scarlett 2i2 4th Gen"
    demo = "Scarlett Gen 4 2i2"
    port_names = frozen(
        {
            ANALOGUE_IN: ("Mic/Line/Inst 1", "Mic/Line/Inst 2"),
            ANALOGUE_OUT: ("Line 1/Headphones (L)", "Line 2/Headphones (R)"),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_IN: INST_12,
            ANALOGUE_OUT: ("Line 1–2/Headphones",),
        }
    )


class Scarlett4i4Gen4(ScarlettGen4):
    pid = 0x821A
    name = "Scarlett 4i4 4th Gen"
    demo = "Scarlett Gen 4 4i4"
    port_names = frozen(
        {
            ANALOGUE_IN: ("Mic/Line/Inst 1", "Mic/Line/Inst 2", "Line 3", "Line 4"),
            ANALOGUE_OUT: (
                "Line 1",
                "Line 2",
                "Line 3",
                "Line 4",
                "Headphones (L)",
                "Headphones (R)",
            ),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_IN: INST_12_LINE_34,
            ANALOGUE_OUT: ("Line 1–2", "Line 3–4", "Headphones"),
        }
    )


class Scarlett16i16Gen4(ScarlettGen4):
    pid = 0x821B
    name = "Scarlett 16i16 4th Gen"
    demo = "Scarlett Gen 4 16i16"
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
            ANALOGUE_IN: INST_12_LINE_3456,
            ANALOGUE_OUT: ("Line 1–2", "Line 3–4", "Headphones 1", "Headphones 2"),
        }
    )
    digital_io_control = "Digital I/O Mode"
    digital_io_help = (
        "Digital I/O Mode selects whether the optical ports are used for ADAT or S/PDIF. In "
        "ADAT mode, S/PDIF is available on the coaxial (RCA) connectors. In Optical S/PDIF "
        "mode, the RCA S/PDIF input is disabled. This requires a reboot to take effect."
    )
    digital_io = frozen(
        {
            "ADAT": DigitalIo((2, 2, 2), (2, 2, 2), (8, 4, 0), (8, 4, 0)),
            "Optical S/PDIF": DigitalIo((4, 4, 0), (4, 4, 2), (0, 0, 0), (0, 0, 0)),
        }
    )


class Scarlett18i16Gen4(ScarlettGen4):
    pid = 0x821C
    name = "Scarlett 18i16 4th Gen"
    demo = "Scarlett Gen 4 18i16"
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
    digital_io_control = "Digital I/O Mode"
    digital_io_help = (
        "Digital I/O Mode selects whether the optical ports are used for ADAT or S/PDIF. In "
        "ADAT mode, S/PDIF is available on the coaxial (RCA) connectors. In Optical S/PDIF "
        "mode, the RCA S/PDIF input is disabled. This requires a reboot to take effect."
    )
    digital_io = frozen(
        {
            "ADAT": DigitalIo((2, 2, 2), (2, 2, 2), (8, 4, 0), (8, 4, 0)),
            "Optical S/PDIF": DigitalIo((4, 4, 0), (4, 4, 2), (0, 0, 0), (0, 0, 0)),
        }
    )


class Scarlett18i20Gen4(ScarlettGen4):
    pid = 0x821D
    name = "Scarlett 18i20 4th Gen"
    demo = "Scarlett Gen 4 18i20"
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
                "Line 1",
                "Line 2",
                "Line 3",
                "Line 4",
                "Line 5",
                "Line 6",
                "Line 7",
                "Line 8",
                "Line 9",
                "Line 10",
                "Headphones 1 (L)",
                "Headphones 1 (R)",
                "Headphones 2 (L)",
                "Headphones 2 (R)",
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
                "Line 7–8",
                "Line 9–10",
                "Headphones 1",
                "Headphones 2",
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
            "RCA S/PDIF": DigitalIo((2, 2, 0), (2, 2, 2), (8, 4, 0), (8, 4, 0)),
            "Optical S/PDIF": DigitalIo((4, 4, 0), (4, 4, 2), (8, 4, 0), (8, 4, 0)),
            "Dual ADAT": DigitalIo((0, 0, 0), (2, 2, 2), (16, 8, 0), (16, 8, 0)),
        }
    )

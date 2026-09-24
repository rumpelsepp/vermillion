# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vocaster (Scarlett2 driver): podcast interfaces with a DSP."""

from vermilion.core.products.base import (
    ANALOGUE_IN,
    ANALOGUE_OUT,
    DSP_OUT,
    MIX_OUT,
    PCM_IN,
    PCM_OUT,
    Product,
    frozen,
)


class Vocaster(Product):
    family = "Vocaster"


class VocasterOne(Vocaster):
    pid = 0x8216
    name = "Vocaster One"
    demo = "Vocaster One"
    port_names = frozen(
        {
            ANALOGUE_IN: ("Host", "Aux"),
            ANALOGUE_OUT: ("Spkr/Headphones (L)", "Spkr/Headphones (R)", "Aux (L)", "Aux (R)"),
            DSP_OUT: ("Host",),
            MIX_OUT: (
                "Show Mix Pre (L)",
                "Show Mix Pre (R)",
                "Aux (L)",
                "Aux (R)",
                "Video Call (L)",
                "Video Call (R)",
                "Show Mix Post (L)",
                "Show Mix Post (R)",
            ),
            PCM_OUT: ("Video Call (L)", "Video Call (R)", "Playback (L)", "Playback (R)"),
            PCM_IN: (
                "Video Call (L)",
                "Video Call (R)",
                "Show Mix (L)",
                "Show Mix (R)",
                "Host Microphone",
                "Aux",
                "Loopback 1 (L)",
                "Loopback 1 (R)",
                "Loopback 2 (L)",
                "Loopback 2 (R)",
            ),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_OUT: ("Spkr/Headphones", "Aux"),
            PCM_OUT: ("Video Call", "Playback"),
            PCM_IN: ("Video Call", "Show Mix", "Host/Aux", "Loopback 1", "Loopback 2"),
            MIX_OUT: ("Show Mix Pre", "Aux", "Video Call", "Show Mix Post"),
        }
    )


class VocasterTwo(Vocaster):
    pid = 0x8217
    name = "Vocaster Two"
    demo = "Vocaster Two"
    port_names = frozen(
        {
            ANALOGUE_IN: ("Host", "Guest", "Aux (L)", "Aux (R)", "Bluetooth (L)", "Bluetooth (R)"),
            ANALOGUE_OUT: (
                "Spkr/Headphones (L)",
                "Spkr/Headphones (R)",
                "Aux (L)",
                "Aux (R)",
                "Bluetooth (L)",
                "Bluetooth (R)",
            ),
            DSP_OUT: ("Host", "Guest"),
            MIX_OUT: (
                "Show Mix Pre (L)",
                "Show Mix Pre (R)",
                "Aux (L)",
                "Aux (R)",
                "Bluetooth (L)",
                "Bluetooth (R)",
                "Video Call (L)",
                "Video Call (R)",
                "Show Mix Post (L)",
                "Show Mix Post (R)",
            ),
            PCM_OUT: ("Video Call (L)", "Video Call (R)", "Playback (L)", "Playback (R)"),
            PCM_IN: (
                "Video Call (L)",
                "Video Call (R)",
                "Show Mix (L)",
                "Show Mix (R)",
                "Host Microphone",
                "Guest Microphone",
                "Aux (L)",
                "Aux (R)",
                "Bluetooth (L)",
                "Bluetooth (R)",
                "Loopback 1 (L)",
                "Loopback 1 (R)",
                "Loopback 2 (L)",
                "Loopback 2 (R)",
            ),
        }
    )
    pair_names = frozen(
        {
            ANALOGUE_IN: ("Mic 1-2", "Aux", "Bluetooth"),
            ANALOGUE_OUT: ("Spkr/Headphones", "Aux", "Bluetooth"),
            PCM_OUT: ("Video Call", "Playback"),
            PCM_IN: (
                "Video Call",
                "Show Mix",
                "Mic 1-2",
                "Aux",
                "Bluetooth",
                "Loopback 1",
                "Loopback 2",
            ),
            DSP_OUT: ("Mic 1-2",),
            MIX_OUT: ("Show Mix Pre", "Aux", "Bluetooth", "Video Call", "Show Mix Post"),
        }
    )

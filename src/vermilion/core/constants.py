# SPDX-FileCopyrightText: 2022-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

from enum import IntEnum, IntFlag

# maximum number of mix outputs
MAX_MIX_OUT = 12

# maximum number of mux inputs (4th Gen 18i20 has 53)
MAX_MUX_IN = 53

# simulated cards have card.num set to -1
SIMULATED_CARD_NUM = -1


class PC(IntEnum):
    """Port categories; must match the level meter ordering from the driver."""

    OFF = 0  # the source when a sink is not connected
    HW = 1  # hardware inputs/outputs
    MIX = 2  # mixer inputs/outputs
    DSP = 3  # DSP inputs/outputs
    PCM = 4  # PCM inputs/outputs


PC_COUNT = 5

PORT_CATEGORY_NAMES: list[str | None] = [
    None,
    "Hardware Outputs",
    "Mixer Inputs",
    "DSP Inputs",
    "PCM Inputs",
]
PORT_CATEGORY_SHORT_NAMES = ["OFF", "HW", "MIX", "DSP", "PCM"]


class HW(IntEnum):
    ANALOGUE = 0
    SPDIF = 1
    ADAT = 2


HW_TYPE_NAMES = ["Analogue", "S/PDIF", "ADAT"]


def is_digital_io_type(hw_type: int) -> bool:
    return hw_type in (HW.SPDIF, HW.ADAT)


class Driver(IntEnum):
    # NONE is 1st Gen or Scarlett2 before hwdep support was added
    # (no erase config or firmware update support)
    NONE = 0
    HWDEP = 1  # Scarlett2 driver with hwdep support
    FCP = 2  # FCP driver: not supported yet (see device.driver)


class UiUpdate(IntFlag):
    """Flags for Card.schedule_ui_update()."""

    MIXER_GRID = 1 << 0
    MONITOR_GROUPS = 1 << 1


# why a port is unavailable (tooltips)
UNAVAILABLE_SAMPLE_RATE = "Unavailable at current sample rate"
UNAVAILABLE_MIXER = "Mixer unavailable at current sample rate"
UNAVAILABLE_DIGITAL = "Unavailable with current Digital I/O mode and sample rate"


class SpeakerSwitch(IntEnum):
    OFF = 0
    MAIN = 1
    ALT = 2


class SR(IntEnum):
    """Sample rate categories."""

    LOW = 0  # 44.1/48 kHz
    MID = 1  # 88.2/96 kHz
    HIGH = 2  # 176.4/192 kHz


def get_sample_rate_category(sample_rate: int) -> SR:
    if sample_rate <= 50000:
        return SR.LOW
    if sample_rate <= 100000:
        return SR.MID
    return SR.HIGH

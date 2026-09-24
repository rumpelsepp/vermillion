# SPDX-FileCopyrightText: 2023-2025 Geoffrey D. Bennett <g@b4.vu> (original C implementation)
# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The two kernel drivers of the interfaces and how to talk to them.

detect() finds out which one a card has, from its hwdep interface.

The Scarlett2 driver implements the controls of the interface as ALSA
controls; its hwdep interface (ioctls) is for maintenance only (reboot,
reset of the configuration).

The FCP (Focusrite Control Protocol) driver is not supported yet. It
leaves nearly everything to user space: its hwdep interface passes the
vendor-specific FCP commands through to the device, and a user-space
driver has to create the ALSA controls from them (the level meter is
the only control of the kernel driver). The large Scarlett 4th Gen
interfaces (16i16, 18i16, 18i20) need it. The reference for the
protocol:

- the kernel driver (Linux 6.14 or later), whose top comment describes
  the use of the hwdep interface:
  https://github.com/torvalds/linux/blob/master/sound/usb/fcp.c
- its ioctls (FCP_IOCTL_PVERSION, _INIT, _CMD, _SET_METER_MAP,
  _SET_METER_LABELS):
  https://github.com/torvalds/linux/blob/master/include/uapi/sound/fcp.h
- the user-space driver fcp-server of fcp-support (by the author of the
  original), with the FCP commands and the controls built from them:
  https://github.com/geoffreybennett/fcp-support
"""

import ctypes
import errno
import logging
from typing import Self

from vermilion.core.asound import Hwdep
from vermilion.core.constants import Driver

_log = logging.getLogger(__name__)

# Scarlett2 hwdep ioctls


def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("S") << 8) | nr


_IOC_NONE, _IOC_WRITE, _IOC_READ = 0, 1, 2

IOCTL_PVERSION = _ioc(_IOC_READ, 0x60, 4)
IOCTL_REBOOT = _ioc(_IOC_NONE, 0x61, 0)
IOCTL_SELECT_FLASH_SEGMENT = _ioc(_IOC_WRITE, 0x62, 4)
IOCTL_ERASE_FLASH_SEGMENT = _ioc(_IOC_NONE, 0x63, 0)
IOCTL_GET_ERASE_PROGRESS = _ioc(_IOC_READ, 0x64, 2)

SEGMENT_ID_SETTINGS = 0

HWDEP_VERSION_MAJOR_SCARLETT2 = 1
HWDEP_VERSION_MAJOR_FCP = 2

# erase_progress() when erasing is complete
ERASE_DONE = 255


class _EraseProgress(ctypes.Structure):
    _fields_ = [("progress", ctypes.c_ubyte), ("num_blocks", ctypes.c_ubyte)]


class Scarlett2Hwdep:
    """The hwdep interface of a card: ioctls of the Scarlett2 driver.
    The methods return negative error codes."""

    def __init__(self, hwdep: Hwdep) -> None:
        self.hwdep = hwdep

    @classmethod
    def open(cls, device: str) -> tuple[Self | None, int]:
        hwdep, err = Hwdep.open(device)
        return (cls(hwdep) if hwdep and err >= 0 else None), err

    def close(self) -> None:
        self.hwdep.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def protocol_version(self) -> int:
        v = ctypes.c_int(0)
        err = self.hwdep.ioctl(IOCTL_PVERSION, v)
        return err if err < 0 else v.value

    def reboot(self) -> int:
        return self.hwdep.ioctl(IOCTL_REBOOT)

    def erase_settings(self) -> int:
        err = self.hwdep.ioctl(IOCTL_SELECT_FLASH_SEGMENT, ctypes.c_int(SEGMENT_ID_SETTINGS))
        if err < 0:
            return err
        return self.hwdep.ioctl(IOCTL_ERASE_FLASH_SEGMENT)

    def erase_progress(self) -> int:
        """0..100 while erasing, ERASE_DONE when complete."""
        p = _EraseProgress()
        err = self.hwdep.ioctl(IOCTL_GET_ERASE_PROGRESS, p)
        if err < 0:
            return err
        progress, num_blocks = int(p.progress), int(p.num_blocks)
        if num_blocks == 0 or progress in (0, ERASE_DONE):
            return progress
        return (progress - 1) * 100 // num_blocks


def detect(device: str) -> Driver:
    """The driver of a card (an ALSA device such as "hw:0"), from its
    hwdep interface."""
    hwdep, err = Hwdep.open(device)
    if err == -errno.ENOENT:
        return Driver.NONE
    # the FCP driver's hwdep interface needs CAP_SYS_RAWIO, and only one
    # user-space driver (such as fcp-server) can have it open
    if err in (-errno.EPERM, -errno.EBUSY):
        return Driver.FCP
    if err < 0 or hwdep is None:
        return Driver.NONE

    with Scarlett2Hwdep(hwdep) as scarlett2:
        ver = scarlett2.protocol_version()
    if ver < 0:
        return Driver.NONE
    major = (ver >> 16) & 0xFF
    if major == HWDEP_VERSION_MAJOR_SCARLETT2:
        return Driver.HWDEP
    if major == HWDEP_VERSION_MAJOR_FCP:
        return Driver.FCP
    return Driver.NONE

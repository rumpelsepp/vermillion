# SPDX-FileCopyrightText: 2026 Stefan Tatschner <stefan.tatschner@mailbox.org>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Driver detection and maintenance operations against fake drivers."""

import ctypes
import errno
from pathlib import Path
from typing import Self

import pytest

from vermilion.core import sim
from vermilion.core.asound import Hwdep
from vermilion.core.card import Card
from vermilion.core.constants import Driver
from vermilion.core.device import driver
from vermilion.core.device.maintenance import (
    Maintenance,
    Reporter,
    Scarlett2Maintenance,
)

DEMO = Path(__file__).parents[1].joinpath("demo", "Scarlett Gen 3 18i8.state")


class Recorder(Reporter):
    """A Reporter that records instead of going through the main loop."""

    def __init__(self) -> None:
        super().__init__(lambda _t, _p: None, lambda: None)
        self.events: list[tuple[str | None, int] | str] = []

    def progress(self, text: str | None, percent: int) -> None:
        self.events.append((text, percent))

    def reboot(self) -> None:
        self.events.append("reboot")


def card(driver_type: Driver) -> Card:
    c = sim.load_card(DEMO)
    c.driver_type = driver_type
    return c


def test_implementation_by_driver() -> None:
    assert isinstance(Maintenance.of(card(Driver.HWDEP)), Scarlett2Maintenance)
    assert Maintenance.of(card(Driver.FCP)) is None
    assert Maintenance.of(card(Driver.NONE)) is None


class FakeHwdep:
    """Erases in three steps."""

    def __init__(self) -> None:
        self.progress = iter([0, 40, 80, driver.ERASE_DONE])
        self.calls: list[str] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append("close")

    def erase_settings(self) -> int:
        self.calls.append("erase")
        return 0

    def erase_progress(self) -> int:
        return next(self.progress)

    def reboot(self) -> int:
        self.calls.append("reboot")
        return 0


def test_scarlett2_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    hwdep = FakeHwdep()
    monkeypatch.setattr(Scarlett2Maintenance, "_open", lambda _self: hwdep)
    monkeypatch.setattr("vermilion.core.device.maintenance.time.sleep", lambda _s: None)
    reporter = Recorder()
    Scarlett2Maintenance(card(Driver.HWDEP)).reset_config(reporter)
    assert reporter.events == [
        ("Resetting configuration...", 0),
        (None, 0),
        (None, 40),
        (None, 80),
        "reboot",
    ]
    assert hwdep.calls == ["erase", "reboot", "close"]


class VersionHwdep:
    """Answers the protocol version ioctl."""

    def __init__(self, major: int) -> None:
        self.major = major

    def ioctl(self, _request: int, arg: ctypes.c_int) -> int:
        arg.value = self.major << 16
        return 0

    def close(self) -> None:
        pass


@pytest.mark.parametrize(
    ("hwdep", "err", "expected"),
    [
        (None, -errno.ENOENT, Driver.NONE),
        (None, -errno.EPERM, Driver.FCP),  # needs CAP_SYS_RAWIO
        (None, -errno.EBUSY, Driver.FCP),  # a user-space driver has it
        (VersionHwdep(driver.HWDEP_VERSION_MAJOR_SCARLETT2), 0, Driver.HWDEP),
        (VersionHwdep(driver.HWDEP_VERSION_MAJOR_FCP), 0, Driver.FCP),
    ],
)
def test_detect(
    hwdep: VersionHwdep | None, err: int, expected: Driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Hwdep, "open", staticmethod(lambda _device: (hwdep, err)))
    assert driver.detect("hw:0") == expected

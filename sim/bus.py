from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class MemoryBus(Protocol):
    """Width-aware interface used by the CPU to access memory."""

    def read8(self, address: int) -> int: ...

    def read16(self, address: int) -> int: ...

    def read32(self, address: int) -> int: ...

    def write8(self, address: int, value: int) -> None: ...

    def write16(self, address: int, value: int) -> None: ...

    def write32(self, address: int, value: int) -> None: ...

    def validate_access(self, address: int, width: int, write: bool = False) -> None: ...


@dataclass(frozen=True)
class _MemoryRegion:
    base_address: int
    size: int
    backing: MemoryBus
    backing_base_address: int
    readable: bool
    writable: bool
    loader_writable: bool

    @property
    def end_address(self) -> int:
        return self.base_address + self.size


class MemoryMap:
    """Routes accesses to non-overlapping memory regions."""

    def __init__(self) -> None:
        self._regions: list[_MemoryRegion] = []

    def map_region(
        self,
        base_address: int,
        size: int,
        backing: MemoryBus,
        *,
        backing_base_address: int = 0,
        readable: bool = True,
        writable: bool = True,
        loader_writable: bool | None = None,
    ) -> None:
        if base_address < 0 or size <= 0 or base_address + size > 0x1_0000_0000:
            raise ValueError("Memory region must fit within the 32-bit address space")
        if backing_base_address < 0:
            raise ValueError("Backing base address must be non-negative")
        end_address = base_address + size
        for region in self._regions:
            if base_address < region.end_address and region.base_address < end_address:
                raise ValueError(
                    f"Memory region 0x{base_address:08X}..0x{end_address - 1:08X} "
                    "overlaps an existing mapping"
                )
        self._regions.append(
            _MemoryRegion(
                base_address,
                size,
                backing,
                backing_base_address,
                readable,
                writable,
                writable if loader_writable is None else loader_writable,
            )
        )
        self._regions.sort(key=lambda region: region.base_address)

    def _resolve(
        self, address: int, width: int, write: bool, loader: bool = False
    ) -> tuple[_MemoryRegion, int]:
        if width <= 0:
            raise ValueError("Access width must be positive")
        for region in self._regions:
            if region.base_address <= address < region.end_address:
                if address + width > region.end_address:
                    break
                if write and not (region.loader_writable if loader else region.writable):
                    raise PermissionError(
                        f"{'Loader' if loader else 'Write'} access denied "
                        f"at 0x{address:08X}"
                    )
                if not write and not region.readable:
                    raise PermissionError(
                        f"Read access denied at 0x{address:08X}"
                    )
                translated = (
                    region.backing_base_address + address - region.base_address
                )
                region.backing.validate_access(translated, width, write)
                return region, translated
        raise IndexError(
            f"Address 0x{address:08X} (width {width}) is unmapped or "
            "outside a mapped region"
        )

    def validate_access(self, address: int, width: int, write: bool = False) -> None:
        self._resolve(address, width, write)

    def validate_load_access(self, address: int, size: int) -> None:
        if size < 0:
            raise ValueError("Load size must be non-negative")
        if size:
            self._resolve(address, size, True, loader=True)

    def load_write(self, address: int, data: bytes) -> None:
        """Write a validated image payload through a loader-authorized mapping."""
        self.validate_load_access(address, len(data))
        if not data:
            return
        region, translated = self._resolve(address, len(data), True, loader=True)
        for offset, value in enumerate(data):
            region.backing.write8(translated + offset, value)

    def _read(self, address: int, width: int) -> int:
        region, translated = self._resolve(address, width, False)
        return getattr(region.backing, f"read{width * 8}")(translated)

    def _write(self, address: int, width: int, value: int) -> None:
        region, translated = self._resolve(address, width, True)
        getattr(region.backing, f"write{width * 8}")(translated, value)

    def read8(self, address: int) -> int:
        return self._read(address, 1)

    def read16(self, address: int) -> int:
        return self._read(address, 2)

    def read32(self, address: int) -> int:
        return self._read(address, 4)

    def write8(self, address: int, value: int) -> None:
        self._write(address, 1, value)

    def write16(self, address: int, value: int) -> None:
        self._write(address, 2, value)

    def write32(self, address: int, value: int) -> None:
        self._write(address, 4, value)

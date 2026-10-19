class Memory:
    """Simple little-endian byte-addressed memory for the initial emulator."""

    def __init__(self, size: int = 1024, base_address: int = 0) -> None:
        if size <= 0:
            raise ValueError("Memory size must be positive")
        self.size = size
        self.base_address = base_address
        self._data = bytearray(size)

    def _offset(self, address: int, width: int) -> int:
        offset = address - self.base_address
        if offset < 0 or offset + width > self.size:
            raise IndexError(
                f"Address 0x{address:08X} (width {width}) is outside "
                f"memory range 0x{self.base_address:08X}.."
                f"0x{self.base_address + self.size - 1:08X}"
            )
        return offset

    def validate_access(self, address: int, width: int, write: bool = False) -> None:
        self._offset(address, width)

    def clear(self) -> None:
        self._data[:] = b"\x00" * self.size

    def read8(self, address: int) -> int:
        return self._data[self._offset(address, 1)]

    def read16(self, address: int) -> int:
        offset = self._offset(address, 2)
        return self._data[offset] | (self._data[offset + 1] << 8)

    def read32(self, address: int) -> int:
        offset = self._offset(address, 4)
        return int.from_bytes(self._data[offset:offset + 4], "little")

    def write8(self, address: int, value: int) -> None:
        self._data[self._offset(address, 1)] = value & 0xFF

    def write16(self, address: int, value: int) -> None:
        offset = self._offset(address, 2)
        self._data[offset:offset + 2] = int(value & 0xFFFF).to_bytes(2, "little")

    def write32(self, address: int, value: int) -> None:
        offset = self._offset(address, 4)
        self._data[offset:offset + 4] = int(value & 0xFFFFFFFF).to_bytes(4, "little")

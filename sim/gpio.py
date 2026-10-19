from __future__ import annotations

GPIOA_BASE = 0x40020000
RCC_BASE = 0x40023800
GPIO_REGISTER_BLOCK_SIZE = 0x400

RCC_AHB1ENR_OFFSET = 0x30
RCC_AHB1ENR_GPIOAEN = 1 << 0

GPIO_MODER_OFFSET = 0x00
GPIO_IDR_OFFSET = 0x10
GPIO_ODR_OFFSET = 0x14
GPIO_BSRR_OFFSET = 0x18

GPIO_MODER_RESET = 0xA8000000


class _WordRegisterDevice:
    def validate_access(self, address: int, width: int, write: bool = False) -> None:
        if width != 4:
            raise ValueError("GPIO/RCC accesses must use aligned 32-bit words")
        if address % 4:
            raise ValueError(f"Unaligned GPIO/RCC register access at 0x{address:08X}")

    def read8(self, address: int) -> int:
        self.validate_access(address, 1)
        raise AssertionError("unreachable")

    def read16(self, address: int) -> int:
        self.validate_access(address, 2)
        raise AssertionError("unreachable")

    def read32(self, address: int) -> int:
        self.validate_access(address, 4)
        raise NotImplementedError

    def write8(self, address: int, value: int) -> None:
        self.validate_access(address, 1, write=True)
        raise AssertionError("unreachable")

    def write16(self, address: int, value: int) -> None:
        self.validate_access(address, 2, write=True)
        raise AssertionError("unreachable")

    def write32(self, address: int, value: int) -> None:
        self.validate_access(address, 4, write=True)
        raise NotImplementedError


class RCC(_WordRegisterDevice):
    """Minimal RCC model for the GPIOA AHB1 clock-enable bit."""

    def __init__(self) -> None:
        self.gpioa_enabled = False

    def reset(self) -> None:
        self.gpioa_enabled = False

    def read32(self, address: int) -> int:
        self.validate_access(address, 4)
        if address != RCC_AHB1ENR_OFFSET:
            raise NotImplementedError(
                f"Unsupported RCC register offset 0x{address:03X}"
            )
        return int(self.gpioa_enabled)

    def write32(self, address: int, value: int) -> None:
        self.validate_access(address, 4, write=True)
        if address != RCC_AHB1ENR_OFFSET:
            raise NotImplementedError(
                f"Unsupported RCC register offset 0x{address:03X}"
            )
        unsupported_bits = value & ~RCC_AHB1ENR_GPIOAEN
        if unsupported_bits:
            raise NotImplementedError(
                "RCC AHB1ENR bits other than GPIOAEN are unsupported"
            )
        self.gpioa_enabled = bool(value & RCC_AHB1ENR_GPIOAEN)


class GPIOA(_WordRegisterDevice):
    """Small GPIOA model for input/output modes, data and bit set/reset."""

    def __init__(self, rcc: RCC) -> None:
        self._rcc = rcc
        self.reset()

    def reset(self) -> None:
        self.moder = GPIO_MODER_RESET
        self.odr = 0
        self._external_inputs = [0] * 16

    def _validate_register_access(self, address: int, width: int, write: bool) -> None:
        self.validate_access(address, width, write)
        if not self._rcc.gpioa_enabled:
            raise PermissionError("GPIOA access denied while its RCC clock is disabled")

    def read32(self, address: int) -> int:
        self._validate_register_access(address, 4, False)
        if address == GPIO_MODER_OFFSET:
            return self.moder
        if address == GPIO_IDR_OFFSET:
            levels = 0
            for pin in range(16):
                mode = (self.moder >> (pin * 2)) & 0x3
                level = (self.odr >> pin) & 1 if mode == 1 else self._external_inputs[pin]
                levels |= level << pin
            return levels
        if address == GPIO_ODR_OFFSET:
            return self.odr
        raise NotImplementedError(
            f"Unsupported GPIOA register offset 0x{address:03X}"
        )

    def write32(self, address: int, value: int) -> None:
        self._validate_register_access(address, 4, True)
        if address == GPIO_MODER_OFFSET:
            self.moder = value & 0xFFFFFFFF
            return
        if address == GPIO_ODR_OFFSET:
            self.odr = value & 0xFFFF
            return
        if address == GPIO_BSRR_OFFSET:
            set_mask = value & 0xFFFF
            reset_mask = (value >> 16) & 0xFFFF
            self.odr = ((self.odr & ~reset_mask) | set_mask) & 0xFFFF
            return
        if address == GPIO_IDR_OFFSET:
            raise PermissionError("GPIOA IDR is read-only")
        raise NotImplementedError(
            f"Unsupported GPIOA register offset 0x{address:03X}"
        )

    def set_input_level(self, pin: int, level: bool) -> None:
        self._check_pin(pin)
        self._external_inputs[pin] = int(bool(level))

    def get_output_level(self, pin: int) -> int | None:
        self._check_pin(pin)
        if ((self.moder >> (pin * 2)) & 0x3) != 1:
            return None
        return (self.odr >> pin) & 1

    @staticmethod
    def _check_pin(pin: int) -> None:
        if not 0 <= pin < 16:
            raise ValueError("GPIOA pin must be in range 0..15")

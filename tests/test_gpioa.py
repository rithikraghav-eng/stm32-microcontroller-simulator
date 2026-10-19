import unittest

from sim.gpio import (
    GPIOA_BASE,
    GPIO_BSRR_OFFSET,
    GPIO_IDR_OFFSET,
    GPIO_MODER_OFFSET,
    GPIO_MODER_RESET,
    GPIO_ODR_OFFSET,
    RCC_AHB1ENR_GPIOAEN,
    RCC_AHB1ENR_OFFSET,
    RCC_BASE,
)
from sim.stm32f411re import FLASH_BASE, STM32F411REBoard


class GPIOATests(unittest.TestCase):
    def setUp(self):
        self.board = STM32F411REBoard()

    def enable_gpioa_clock(self):
        self.board.bus.write32(
            RCC_BASE + RCC_AHB1ENR_OFFSET, RCC_AHB1ENR_GPIOAEN
        )

    def test_register_addresses_reset_values_and_clock_gate(self):
        self.assertEqual(GPIOA_BASE, 0x40020000)
        self.assertEqual(RCC_BASE + RCC_AHB1ENR_OFFSET, 0x40023830)
        self.assertEqual(self.board.bus.read32(RCC_BASE + RCC_AHB1ENR_OFFSET), 0)

        with self.assertRaises(PermissionError):
            self.board.bus.read32(GPIOA_BASE + GPIO_MODER_OFFSET)

        self.enable_gpioa_clock()
        self.assertEqual(
            self.board.bus.read32(GPIOA_BASE + GPIO_MODER_OFFSET),
            GPIO_MODER_RESET,
        )
        self.assertEqual(self.board.bus.read32(GPIOA_BASE + GPIO_IDR_OFFSET), 0)
        self.assertEqual(self.board.bus.read32(GPIOA_BASE + GPIO_ODR_OFFSET), 0)

        self.board.bus.write32(RCC_BASE + RCC_AHB1ENR_OFFSET, 0)
        with self.assertRaises(PermissionError):
            self.board.bus.read32(GPIOA_BASE + GPIO_ODR_OFFSET)

    def test_moder_odr_and_effective_output_pin(self):
        self.enable_gpioa_clock()
        moder = self.board.bus.read32(GPIOA_BASE + GPIO_MODER_OFFSET)
        moder = (moder & ~0x3) | 0x1
        moder = (moder & ~(0x3 << 30)) | (0x1 << 30)
        self.board.bus.write32(GPIOA_BASE + GPIO_MODER_OFFSET, moder)
        self.board.bus.write32(GPIOA_BASE + GPIO_ODR_OFFSET, 0x8001)

        self.assertEqual(self.board.bus.read32(GPIOA_BASE + GPIO_ODR_OFFSET), 0x8001)
        self.assertEqual(self.board.gpioa.get_output_level(0), 1)
        self.assertEqual(self.board.gpioa.get_output_level(15), 1)
        self.assertIsNone(self.board.gpioa.get_output_level(1))
        self.assertEqual(
            (self.board.bus.read32(GPIOA_BASE + GPIO_IDR_OFFSET) & 1),
            1,
        )

    def test_bsrr_sets_and_resets_odr_atomically(self):
        self.enable_gpioa_clock()
        self.board.bus.write32(GPIOA_BASE + GPIO_ODR_OFFSET, 0x0003)
        self.board.bus.write32(
            GPIOA_BASE + GPIO_BSRR_OFFSET,
            (1 << 4) | (1 << (16 + 1)),
        )
        self.assertEqual(self.board.bus.read32(GPIOA_BASE + GPIO_ODR_OFFSET), 0x11)

        self.board.bus.write32(
            GPIOA_BASE + GPIO_BSRR_OFFSET,
            (1 << 1) | (1 << (16 + 1)),
        )
        self.assertEqual(self.board.bus.read32(GPIOA_BASE + GPIO_ODR_OFFSET), 0x13)

        with self.assertRaises(NotImplementedError):
            self.board.bus.read32(GPIOA_BASE + GPIO_BSRR_OFFSET)

    def test_external_input_levels_and_input_data_register(self):
        self.enable_gpioa_clock()
        self.board.gpioa.set_input_level(2, True)
        self.board.gpioa.set_input_level(5, True)
        self.assertEqual(
            self.board.bus.read32(GPIOA_BASE + GPIO_IDR_OFFSET),
            (1 << 2) | (1 << 5),
        )

        moder = self.board.bus.read32(GPIOA_BASE + GPIO_MODER_OFFSET)
        moder &= ~(0x3 << (2 * 2))
        self.board.bus.write32(GPIOA_BASE + GPIO_MODER_OFFSET, moder)
        self.assertEqual(self.board.bus.read32(GPIOA_BASE + GPIO_IDR_OFFSET) & 4, 4)
        with self.assertRaises(PermissionError):
            self.board.bus.write32(GPIOA_BASE + GPIO_IDR_OFFSET, 0)

        with self.assertRaises(ValueError):
            self.board.gpioa.set_input_level(16, True)
        with self.assertRaises(ValueError):
            self.board.gpioa.get_output_level(-1)

    def test_invalid_width_alignment_and_unimplemented_registers(self):
        self.enable_gpioa_clock()
        with self.assertRaises(ValueError):
            self.board.bus.read8(GPIOA_BASE)
        with self.assertRaises(ValueError):
            self.board.bus.write16(GPIOA_BASE, 0)
        with self.assertRaises(ValueError):
            self.board.bus.read32(GPIOA_BASE + 1)
        with self.assertRaises(NotImplementedError):
            self.board.bus.read32(GPIOA_BASE + 0x04)
        with self.assertRaises(NotImplementedError):
            self.board.bus.write32(GPIOA_BASE + 0x0C, 0)
        with self.assertRaises(NotImplementedError):
            self.board.bus.write32(
                RCC_BASE + RCC_AHB1ENR_OFFSET,
                RCC_AHB1ENR_GPIOAEN | 0x2,
            )

    def test_cpu_load_store_instructions_access_gpio_through_bus(self):
        self.board.flash.write16(0, 0x6308)  # STR R0, [R1, #12]
        self.board.flash.write16(2, 0x6008)  # STR R0, [R1]
        self.board.flash.write16(4, 0x6148)  # STR R0, [R1, #20]
        self.board.cpu.pc = FLASH_BASE
        self.board.cpu.regs[0] = RCC_AHB1ENR_GPIOAEN
        self.board.cpu.regs[1] = RCC_BASE
        self.board.cpu.step()

        self.board.cpu.regs[0] = 1
        self.board.cpu.regs[1] = GPIOA_BASE
        self.board.cpu.step()
        self.board.cpu.step()

        self.assertEqual(self.board.bus.read32(GPIOA_BASE + GPIO_MODER_OFFSET) & 0x3, 1)
        self.assertEqual(self.board.gpioa.get_output_level(0), 1)

        self.board.flash.write16(6, 0x6948)  # LDR R0, [R1, #20]
        self.board.cpu.step()
        self.assertEqual(self.board.cpu.regs[0], 1)

    def test_board_reset_restores_rcc_gpio_registers_and_input_defaults(self):
        initial_sp = 0x20020000
        self.board.flash.write32(0, initial_sp)
        self.board.flash.write32(4, FLASH_BASE + 9)
        self.enable_gpioa_clock()
        self.board.bus.write32(GPIOA_BASE + GPIO_ODR_OFFSET, 0xFFFF)
        self.board.gpioa.set_input_level(3, True)

        self.board.reset()

        self.assertEqual(self.board.bus.read32(RCC_BASE + RCC_AHB1ENR_OFFSET), 0)
        with self.assertRaises(PermissionError):
            self.board.bus.read32(GPIOA_BASE + GPIO_ODR_OFFSET)
        self.enable_gpioa_clock()
        self.assertEqual(self.board.bus.read32(GPIOA_BASE + GPIO_MODER_OFFSET), GPIO_MODER_RESET)
        self.assertEqual(self.board.bus.read32(GPIOA_BASE + GPIO_ODR_OFFSET), 0)
        self.assertEqual(self.board.bus.read32(GPIOA_BASE + GPIO_IDR_OFFSET), 0)


if __name__ == "__main__":
    unittest.main()

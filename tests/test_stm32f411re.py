import unittest

from sim.stm32f411re import (
    FLASH_BASE,
    FLASH_SIZE,
    SRAM_BASE,
    SRAM_SIZE,
    STM32F411REBoard,
)


class STM32F411REBoardTests(unittest.TestCase):
    def test_flash_and_sram_mapping_boundaries_and_sizes(self):
        board = STM32F411REBoard()
        self.assertEqual(board.flash.size, 512 * 1024)
        self.assertEqual(board.sram.size, 128 * 1024)

        board.flash.write8(FLASH_SIZE - 1, 0xA5)
        self.assertEqual(board.bus.read8(FLASH_BASE + FLASH_SIZE - 1), 0xA5)
        with self.assertRaises(IndexError):
            board.bus.read8(FLASH_BASE + FLASH_SIZE)

        board.bus.write8(SRAM_BASE + SRAM_SIZE - 1, 0x5A)
        self.assertEqual(board.bus.read8(SRAM_BASE + SRAM_SIZE - 1), 0x5A)
        with self.assertRaises(IndexError):
            board.bus.read8(SRAM_BASE + SRAM_SIZE)

    def test_flash_is_read_only_through_bus_and_fetchable_by_cpu(self):
        board = STM32F411REBoard()
        board.flash.write16(8, 0x2007)
        board.flash.write32(4, FLASH_BASE + 9)

        with self.assertRaises(PermissionError):
            board.bus.write8(FLASH_BASE, 0)

        board.cpu.pc = FLASH_BASE + 8
        board.cpu.step()
        self.assertEqual(board.cpu.regs[0], 7)

    def test_sram_is_readable_and_writable(self):
        board = STM32F411REBoard()
        board.bus.write32(SRAM_BASE + 0x20, 0x12345678)
        self.assertEqual(board.bus.read32(SRAM_BASE + 0x20), 0x12345678)

    def test_peripheral_and_other_unmapped_regions_fail(self):
        board = STM32F411REBoard()
        for address in (0x1FFF0000, 0x40000000, 0xE0000000):
            with self.subTest(address=hex(address)):
                with self.assertRaises(IndexError):
                    board.bus.read32(address)

    def test_reset_reads_vectors_clears_sram_and_resets_cpu_but_retains_flash(self):
        board = STM32F411REBoard()
        initial_sp = SRAM_BASE + SRAM_SIZE
        reset_handler = FLASH_BASE + 9
        board.flash.write32(0, initial_sp)
        board.flash.write32(4, reset_handler)
        board.flash.write16(8, 0x200B)
        board.bus.write32(SRAM_BASE, 0xDEADBEEF)
        board.cpu.regs[0] = 0x12345678
        board.cpu.lr = 0x87654321
        board.cpu.N, board.cpu.Z, board.cpu.C, board.cpu.V = 1, 1, 1, 1
        board.cpu.halted = True
        board.cpu.instructions_executed = 9

        board.reset()

        self.assertEqual(board.cpu.sp, initial_sp)
        self.assertEqual(board.cpu.pc, FLASH_BASE + 8)
        self.assertEqual(board.cpu.regs[0], 0)
        self.assertEqual(board.cpu.lr, 0)
        self.assertEqual((board.cpu.N, board.cpu.Z, board.cpu.C, board.cpu.V), (0, 0, 0, 0))
        self.assertFalse(board.cpu.halted)
        self.assertEqual(board.cpu.instructions_executed, 0)
        self.assertEqual(board.bus.read32(SRAM_BASE), 0)
        self.assertEqual(board.bus.read16(FLASH_BASE + 8), 0x200B)

    def test_reset_rejects_non_thumb_reset_vector_without_mutating_state(self):
        board = STM32F411REBoard()
        board.flash.write32(0, SRAM_BASE + SRAM_SIZE)
        board.flash.write32(4, FLASH_BASE + 8)
        board.bus.write32(SRAM_BASE, 0xAABBCCDD)
        board.cpu.regs[0] = 0x11223344

        with self.assertRaises(ValueError):
            board.reset()

        self.assertEqual(board.bus.read32(SRAM_BASE), 0xAABBCCDD)
        self.assertEqual(board.cpu.regs[0], 0x11223344)


if __name__ == "__main__":
    unittest.main()

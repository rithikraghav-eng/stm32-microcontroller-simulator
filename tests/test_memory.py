import unittest
from sim.bus import MemoryMap
from sim.memory import Memory


class MemoryTests(unittest.TestCase):
    def test_little_endian_reads_and_writes(self):
        memory = Memory(size=16)
        memory.write32(0, 0x12345678)
        self.assertEqual(memory.read8(0), 0x78)
        self.assertEqual(memory.read16(0), 0x5678)
        self.assertEqual(memory.read32(0), 0x12345678)

    def test_out_of_bounds_raises(self):
        memory = Memory(size=4)
        with self.assertRaises(IndexError):
            memory.read32(2)

    def test_memory_map_regions_translation_and_widths(self):
        flash = Memory(size=16)
        ram = Memory(size=16)
        memory_map = MemoryMap()
        memory_map.map_region(0x08000000, 16, flash)
        memory_map.map_region(0x20000000, 16, ram, backing_base_address=4)

        memory_map.write32(0x08000000, 0x12345678)
        self.assertEqual(flash.read32(0), 0x12345678)
        memory_map.write16(0x20000002, 0xABCD)
        self.assertEqual(ram.read16(6), 0xABCD)
        self.assertEqual(memory_map.read8(0x20000002), 0xCD)
        self.assertEqual(memory_map.read16(0x20000002), 0xABCD)
        self.assertEqual(memory_map.read32(0x08000000), 0x12345678)

    def test_memory_map_rejects_unmapped_and_cross_boundary_accesses(self):
        memory_map = MemoryMap()
        memory_map.map_region(0x1000, 4, Memory(size=4))

        with self.assertRaises(IndexError):
            memory_map.read8(0x2000)
        with self.assertRaises(IndexError):
            memory_map.read32(0x1002)
        with self.assertRaises(IndexError):
            memory_map.read8(0x1004)

    def test_memory_map_access_permissions_and_overlapping_regions(self):
        backing = Memory(size=8)
        backing.write8(0, 0x34)
        memory_map = MemoryMap()
        memory_map.map_region(0x3000, 8, backing, writable=False)
        self.assertEqual(memory_map.read8(0x3000), 0x34)
        with self.assertRaises(PermissionError):
            memory_map.write8(0x3000, 0x12)
        with self.assertRaises(ValueError):
            memory_map.map_region(0x3004, 8, Memory(size=8))

        write_only = MemoryMap()
        write_only.map_region(0x4000, 8, Memory(size=8), readable=False)
        with self.assertRaises(PermissionError):
            write_only.read8(0x4000)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from sim.elf import (
    ELF32_HEADER,
    ELF32_PROGRAM_HEADER,
    ELFError,
    parse_elf32_arm,
)
from sim.stm32f411re import (
    FLASH_BASE,
    RCC_BASE,
    SRAM_BASE,
    SRAM_SIZE,
    FirmwareExecutionError,
    FirmwareLoadError,
    STM32F411REBoard,
)


def make_elf(
    *,
    elf_class=1,
    endianness=1,
    elf_type=2,
    machine=40,
    entry=0x08000001,
    segments=None,
):
    if segments is None:
        segments = [
            {
                "offset": 0x100,
                "vaddr": 0x08000000,
                "paddr": 0x08000000,
                "data": b"\x00\x20\x01\x30",
                "memsz": 8,
                "flags": 5,
                "align": 0x100,
                "type": 1,
            }
        ]
    ident = bytearray(b"\x7fELF" + bytes([elf_class, endianness, 1, 0, 0]) + bytes(7))
    program_header_offset = ELF32_HEADER.size
    table_end = program_header_offset + ELF32_PROGRAM_HEADER.size * len(segments)
    file_size = max(table_end, 0x200)
    for segment in segments:
        segment_end = segment["offset"] + len(segment["data"])
        if segment_end <= 0x100000:
            file_size = max(file_size, segment_end)

    image = bytearray(file_size)
    image[:ELF32_HEADER.size] = ELF32_HEADER.pack(
        bytes(ident),
        elf_type,
        machine,
        1,
        entry,
        program_header_offset,
        0,
        0,
        ELF32_HEADER.size,
        ELF32_PROGRAM_HEADER.size,
        len(segments),
        0,
        0,
        0,
    )
    for index, segment in enumerate(segments):
        segment_offset = segment["offset"]
        file_data = segment["data"]
        header_offset = program_header_offset + index * ELF32_PROGRAM_HEADER.size
        image[header_offset:header_offset + ELF32_PROGRAM_HEADER.size] = (
            ELF32_PROGRAM_HEADER.pack(
                segment.get("type", 1),
                segment_offset,
                segment["vaddr"],
                segment["paddr"],
                len(file_data),
                segment["memsz"],
                segment["flags"],
                segment["align"],
            )
        )
        if segment_offset + len(file_data) <= len(image):
            image[segment_offset:segment_offset + len(file_data)] = file_data
    return image


class ELFParserTests(unittest.TestCase):
    def test_parse_loadable_arm_executable_and_segment_fields(self):
        image = parse_elf32_arm(make_elf())

        self.assertEqual(image.entry_point, 0x08000001)
        self.assertEqual(len(image.segments), 1)
        segment = image.segments[0]
        self.assertEqual(segment.virtual_address, 0x08000000)
        self.assertEqual(segment.physical_address, 0x08000000)
        self.assertEqual(segment.load_address, 0x08000000)
        self.assertEqual(segment.file_size, 4)
        self.assertEqual(segment.memory_size, 8)
        self.assertEqual(segment.data, b"\x00\x20\x01\x30")

    def test_reject_invalid_header_class_endianness_type_and_architecture(self):
        cases = [
            (make_elf(elf_class=2), "ELF32"),
            (make_elf(endianness=2), "little-endian"),
            (make_elf(elf_type=1), "executable"),
            (make_elf(machine=3), "architecture"),
            (b"\x7fELF", "Truncated"),
            (bytearray(b"invalid input".ljust(52, b"\0")), "magic"),
        ]
        for fixture, message in cases:
            with self.subTest(error=message):
                with self.assertRaisesRegex(ELFError, message):
                    parse_elf32_arm(fixture)

    def test_reject_malformed_program_header_tables(self):
        truncated = make_elf()
        truncated[28:32] = struct.pack("<I", 0xFFFFFFF0)
        with self.assertRaisesRegex(ELFError, "(?i)program header table"):
            parse_elf32_arm(truncated)

        wrong_entry_size = make_elf()
        wrong_entry_size[42:44] = struct.pack("<H", 31)
        with self.assertRaisesRegex(ELFError, "program header size"):
            parse_elf32_arm(wrong_entry_size)

    def test_reject_invalid_load_segment_ranges_and_alignment(self):
        cases = [
            (
                [{"offset": 0x100, "vaddr": 0x08000000, "paddr": 0x08000000,
                  "data": b"1234", "memsz": 2, "flags": 5, "align": 1}],
                "p_filesz",
            ),
            (
                [{"offset": 0x100, "vaddr": 0x08000000, "paddr": 0x08000000,
                  "data": b"1234", "memsz": 4, "flags": 5, "align": 3}],
                "power of two",
            ),
            (
                [{"offset": 0x100, "vaddr": 0x08000001, "paddr": 0x08000001,
                  "data": b"1234", "memsz": 4, "flags": 5, "align": 0x100}],
                "incongruent",
            ),
            (
                [{"offset": 0xFFFFFFFE, "vaddr": 0x08000000, "paddr": 0x08000000,
                  "data": b"1234", "memsz": 4, "flags": 5, "align": 1}],
                "outside the ELF file",
            ),
            (
                [{"offset": 0x100, "vaddr": 0xFFFFFFFE, "paddr": 0xFFFFFFFE,
                  "data": b"", "memsz": 4, "flags": 5, "align": 1}],
                "virtual range overflows",
            ),
        ]
        for segments, message in cases:
            with self.subTest(error=message):
                with self.assertRaisesRegex(ELFError, message):
                    parse_elf32_arm(make_elf(segments=segments))

    def test_entry_must_be_inside_executable_load_segment(self):
        with self.assertRaisesRegex(ELFError, "entry point"):
            parse_elf32_arm(make_elf(entry=0x08000020))
        with self.assertRaisesRegex(ELFError, "entry point"):
            parse_elf32_arm(
                make_elf(
                    segments=[
                        {
                            "offset": 0x100,
                            "vaddr": 0x08000000,
                            "paddr": 0x08000000,
                            "data": b"\x00\x20",
                            "memsz": 2,
                            "flags": 4,
                            "align": 1,
                        }
                    ]
                )
            )

    def test_reject_dynamic_and_no_loadable_segments(self):
        dynamic = make_elf(
            segments=[
                {
                    "offset": 0x100,
                    "vaddr": 0x08000000,
                    "paddr": 0x08000000,
                    "data": b"",
                    "memsz": 0,
                    "flags": 5,
                    "align": 1,
                    "type": 2,
                }
            ]
        )
        with self.assertRaisesRegex(ELFError, "Dynamic linking"):
            parse_elf32_arm(dynamic)

        empty = make_elf(
            segments=[
                {
                    "offset": 0x100,
                    "vaddr": 0x08000000,
                    "paddr": 0x08000000,
                    "data": b"",
                    "memsz": 0,
                    "flags": 0,
                    "align": 1,
                    "type": 0,
                }
            ]
        )
        with self.assertRaisesRegex(ELFError, "no loadable"):
            parse_elf32_arm(empty)

    def test_load_address_falls_back_to_virtual_address_when_paddr_zero(self):
        image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": 0x08000000,
                        "paddr": 0,
                        "data": b"\x00\x20",
                        "memsz": 2,
                        "flags": 5,
                        "align": 1,
                    }
                ]
            )
        )
        self.assertEqual(image.segments[0].load_address, 0x08000000)

    def test_board_loads_flash_segment_without_changing_cpu_or_reset_state(self):
        board = STM32F411REBoard()
        board.cpu.pc = 0x1234
        board.cpu.sp = SRAM_BASE + 0x100
        board.cpu.regs[0] = 0xAABBCCDD
        board.cpu.N, board.cpu.Z, board.cpu.C, board.cpu.V = 1, 1, 0, 1
        board.cpu.instructions_executed = 17
        board.flash.write32(0, SRAM_BASE + 0x20000)
        board.flash.write32(4, FLASH_BASE + 0x121)

        image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": FLASH_BASE + 0x100,
                        "paddr": FLASH_BASE + 0x100,
                        "data": b"\x00\x20\x01\x30",
                        "memsz": 8,
                        "flags": 5,
                        "align": 0x100,
                    }
                ],
                entry=FLASH_BASE + 0x101,
            )
        )
        result = board.load_firmware(image)

        self.assertEqual(result.entry_point, image.entry_point)
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(
            (result.segments[0].address, result.segments[0].file_size,
             result.segments[0].memory_size),
            (FLASH_BASE + 0x100, 4, 8),
        )
        self.assertEqual(board.bus.read32(FLASH_BASE + 0x100), 0x30012000)
        self.assertEqual(board.bus.read32(FLASH_BASE + 0x104), 0)
        self.assertEqual(board.cpu.pc, 0x1234)
        self.assertEqual(board.cpu.sp, SRAM_BASE + 0x100)
        self.assertEqual(board.cpu.regs[0], 0xAABBCCDD)
        self.assertEqual((board.cpu.N, board.cpu.Z, board.cpu.C, board.cpu.V), (1, 1, 0, 1))
        self.assertEqual(board.cpu.instructions_executed, 17)
        with self.assertRaises(PermissionError):
            board.bus.write8(FLASH_BASE, 0xFF)

        board.reset()
        self.assertEqual(board.cpu.pc, FLASH_BASE + 0x120)
        self.assertEqual(board.cpu.sp, SRAM_BASE + 0x20000)

    def test_board_loads_multiple_segments_and_zeroes_memory_tail(self):
        board = STM32F411REBoard()
        image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x200,
                        "vaddr": FLASH_BASE + 0x100,
                        "paddr": FLASH_BASE + 0x200,
                        "data": b"\xAA\xBB",
                        "memsz": 4,
                        "flags": 5,
                        "align": 1,
                    },
                    {
                        "offset": 0x210,
                        "vaddr": SRAM_BASE + 0x20,
                        "paddr": SRAM_BASE + 0x20,
                        "data": b"\x11\x22\x33",
                        "memsz": 8,
                        "flags": 6,
                        "align": 1,
                    },
                ],
                entry=FLASH_BASE + 0x101,
            )
        )
        board.sram.write32(0x20, 0xFFFFFFFF)
        board.sram.write32(0x24, 0xFFFFFFFF)

        result = board.load_firmware(image)

        self.assertEqual(
            [segment.address for segment in result.segments],
            [FLASH_BASE + 0x200, SRAM_BASE + 0x20],
        )
        self.assertEqual(board.bus.read32(FLASH_BASE + 0x200), 0x0000BBAA)
        self.assertEqual(board.bus.read32(SRAM_BASE + 0x20), 0x00332211)
        self.assertEqual(board.bus.read32(SRAM_BASE + 0x24), 0)

    def test_board_copies_initialized_data_from_flash_load_address_to_sram(self):
        board = STM32F411REBoard()
        image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": FLASH_BASE,
                        "paddr": FLASH_BASE,
                        "data": b"\x00\x20",
                        "memsz": 2,
                        "flags": 5,
                        "align": 1,
                    },
                    {
                        "offset": 0x110,
                        "vaddr": SRAM_BASE + 0x20,
                        "paddr": FLASH_BASE + 0x200,
                        "data": b"\x78\x56\x34\x12",
                        "memsz": 12,
                        "flags": 6,
                        "align": 1,
                    },
                ],
                entry=FLASH_BASE + 1,
            )
        )
        board.sram.write32(0x20, 0xFFFFFFFF)
        board.sram.write32(0x24, 0xFFFFFFFF)
        board.sram.write32(0x28, 0xFFFFFFFF)

        result = board.load_firmware(image)

        self.assertEqual(board.bus.read32(FLASH_BASE + 0x200), 0x12345678)
        self.assertEqual(board.bus.read32(SRAM_BASE + 0x20), 0x12345678)
        self.assertEqual(board.bus.read32(SRAM_BASE + 0x24), 0)
        self.assertEqual(board.bus.read32(SRAM_BASE + 0x28), 0)
        self.assertEqual(
            (result.segments[1].address, result.segments[1].runtime_address),
            (FLASH_BASE + 0x200, SRAM_BASE + 0x20),
        )
        with self.assertRaises(PermissionError):
            board.bus.write32(FLASH_BASE + 0x200, 0)

    def test_board_loader_validates_runtime_destination_before_any_write(self):
        board = STM32F411REBoard()
        board.flash.write32(0x100, 0xAABBCCDD)
        board.sram.write32(0x20, 0x11223344)
        image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": FLASH_BASE + 0x100,
                        "paddr": FLASH_BASE + 0x100,
                        "data": b"CODE",
                        "memsz": 4,
                        "flags": 5,
                        "align": 1,
                    },
                    {
                        "offset": 0x110,
                        "vaddr": 0x40000000,
                        "paddr": FLASH_BASE + 0x200,
                        "data": b"DATA",
                        "memsz": 8,
                        "flags": 6,
                        "align": 1,
                    },
                ],
                entry=FLASH_BASE + 0x101,
            )
        )

        with self.assertRaisesRegex(FirmwareLoadError, "runtime range is not loadable"):
            board.load_firmware(image)

        self.assertEqual(board.bus.read32(FLASH_BASE + 0x100), 0xAABBCCDD)
        self.assertEqual(board.bus.read32(FLASH_BASE + 0x200), 0)
        self.assertEqual(board.bus.read32(SRAM_BASE + 0x20), 0x11223344)

    def test_board_loader_rejects_overlapping_runtime_ranges_atomically(self):
        board = STM32F411REBoard()
        image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": FLASH_BASE,
                        "paddr": FLASH_BASE,
                        "data": b"\x00\x20",
                        "memsz": 2,
                        "flags": 5,
                        "align": 1,
                    },
                    {
                        "offset": 0x110,
                        "vaddr": SRAM_BASE + 0x20,
                        "paddr": FLASH_BASE + 0x200,
                        "data": b"AAAA",
                        "memsz": 4,
                        "flags": 6,
                        "align": 1,
                    },
                    {
                        "offset": 0x120,
                        "vaddr": SRAM_BASE + 0x22,
                        "paddr": FLASH_BASE + 0x210,
                        "data": b"BBBB",
                        "memsz": 4,
                        "flags": 6,
                        "align": 1,
                    },
                ],
                entry=FLASH_BASE + 1,
            )
        )

        with self.assertRaisesRegex(FirmwareLoadError, "overlaps"):
            board.load_firmware(image)

        self.assertEqual(board.bus.read16(FLASH_BASE), 0)
        self.assertEqual(board.bus.read32(FLASH_BASE + 0x200), 0)
        self.assertEqual(board.bus.read32(SRAM_BASE + 0x20), 0)

    def test_board_loader_uses_vaddr_fallback_and_rejects_unmapped_destinations(self):
        board = STM32F411REBoard()
        fallback_image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": FLASH_BASE + 0x40,
                        "paddr": 0,
                        "data": b"\x01\x02",
                        "memsz": 2,
                        "flags": 5,
                        "align": 1,
                    }
                ],
                entry=FLASH_BASE + 0x41,
            )
        )
        fallback_result = board.load_firmware(fallback_image)
        self.assertEqual(fallback_result.segments[0].address, FLASH_BASE + 0x40)
        self.assertEqual(board.bus.read16(FLASH_BASE + 0x40), 0x0201)

        invalid_image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": FLASH_BASE + 0x80,
                        "paddr": FLASH_BASE + 0x80,
                        "data": b"GOOD",
                        "memsz": 4,
                        "flags": 5,
                        "align": 1,
                    },
                    {
                        "offset": 0x110,
                        "vaddr": 0x40000000,
                        "paddr": 0x40000000,
                        "data": b"BAD!",
                        "memsz": 4,
                        "flags": 6,
                        "align": 1,
                    },
                ],
                entry=FLASH_BASE + 0x81,
            )
        )
        before = board.bus.read32(FLASH_BASE + 0x80)
        with self.assertRaisesRegex(FirmwareLoadError, "not loadable"):
            board.load_firmware(invalid_image)
        self.assertEqual(board.bus.read32(FLASH_BASE + 0x80), before)

    def test_board_loader_rejects_flash_overflow_and_malformed_segment_without_partial_load(self):
        board = STM32F411REBoard()
        image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": FLASH_BASE + 0x100,
                        "paddr": FLASH_BASE + 0x100,
                        "data": b"GOOD",
                        "memsz": 4,
                        "flags": 5,
                        "align": 1,
                    },
                    {
                        "offset": 0x110,
                        "vaddr": FLASH_BASE,
                        "paddr": FLASH_BASE + 512 * 1024 - 2,
                        "data": b"END!",
                        "memsz": 4,
                        "flags": 6,
                        "align": 1,
                    },
                ],
                entry=FLASH_BASE + 0x101,
            )
        )
        with self.assertRaisesRegex(FirmwareLoadError, "not loadable"):
            board.load_firmware(image)
        self.assertEqual(board.bus.read32(FLASH_BASE + 0x100), 0)

        malformed = parse_elf32_arm(make_elf())
        bad_segment = malformed.segments[0]
        malformed_image = type(malformed)(
            entry_point=malformed.entry_point,
            flags=malformed.flags,
            segments=(bad_segment, type(bad_segment)(
                offset=0,
                virtual_address=FLASH_BASE + 0x20,
                physical_address=FLASH_BASE + 0x20,
                file_size=3,
                memory_size=4,
                flags=5,
                alignment=1,
                data=b"x",
            )),
        )
        with self.assertRaisesRegex(FirmwareLoadError, "inconsistent"):
            board.load_firmware(malformed_image)
        self.assertEqual(board.bus.read32(FLASH_BASE + 0x20), 0)

    def test_board_loader_rejects_peripheral_destination(self):
        board = STM32F411REBoard()
        image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": FLASH_BASE + 0x100,
                        "paddr": FLASH_BASE + 0x100,
                        "data": b"\x00\x20",
                        "memsz": 2,
                        "flags": 5,
                        "align": 1,
                    },
                    {
                        "offset": 0x110,
                        "vaddr": RCC_BASE + 0x30,
                        "paddr": RCC_BASE + 0x30,
                        "data": b"\x01\x00\x00\x00",
                        "memsz": 4,
                        "flags": 6,
                        "align": 1,
                    },
                ],
                entry=FLASH_BASE + 0x101,
            )
        )
        with self.assertRaisesRegex(FirmwareLoadError, "not loadable"):
            board.load_firmware(image)
        self.assertEqual(board.bus.read16(FLASH_BASE + 0x100), 0)


class TestFirmwareExecutionTests(unittest.TestCase):
    @staticmethod
    def make_image(instructions, *, base=FLASH_BASE + 0x100):
        code = b"".join(struct.pack("<H", instruction) for instruction in instructions)
        return parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": base,
                        "paddr": base,
                        "data": code,
                        "memsz": len(code),
                        "flags": 5,
                        "align": 1,
                    }
                ],
                entry=base + 1,
            )
        )

    def test_test_mode_initializes_cpu_and_executes_until_bkpt(self):
        board = STM32F411REBoard()
        board.sram.write32(0x20, 0xAABBCCDD)
        board.cpu.regs[0] = 0xFFFFFFFF
        board.cpu.N, board.cpu.Z, board.cpu.C, board.cpu.V = 1, 1, 1, 1
        board.cpu.instructions_executed = 99
        image = self.make_image([0x2014, 0x3016, 0xBE00])

        result = board.run_test_firmware(image, max_instructions=2)

        self.assertEqual(result.entry_point, FLASH_BASE + 0x101)
        self.assertEqual(result.initial_stack_pointer, SRAM_BASE + SRAM_SIZE)
        self.assertEqual(result.instructions_executed, 2)
        self.assertEqual(result.registers[0], 42)
        self.assertEqual(result.registers[1], 0)
        self.assertEqual(result.flags, (0, 0, 0, 0))
        self.assertEqual(result.termination, "BKPT #0")
        self.assertEqual(board.cpu.pc, FLASH_BASE + 0x104)
        self.assertEqual(board.sram.read32(0x20), 0xAABBCCDD)

    def test_instruction_budget_exhaustion_reports_pc(self):
        board = STM32F411REBoard()
        image = self.make_image([0x2001, 0xE7FE])

        with self.assertRaisesRegex(
            FirmwareExecutionError,
            r"budget exhausted after 2 instructions at PC 0x08000102",
        ):
            board.run_test_firmware(image, max_instructions=2)

    def test_unsupported_instruction_reports_address_and_encoding(self):
        board = STM32F411REBoard()
        image = self.make_image([0xBE01])

        with self.assertRaisesRegex(
            FirmwareExecutionError,
            r"Unsupported instruction at 0x08000100 \(0xBE01\)",
        ):
            board.run_test_firmware(image)

    def test_test_mode_rejects_entry_not_at_loaded_physical_address(self):
        board = STM32F411REBoard()
        image = parse_elf32_arm(
            make_elf(
                segments=[
                    {
                        "offset": 0x100,
                        "vaddr": FLASH_BASE + 0x100,
                        "paddr": FLASH_BASE + 0x200,
                        "data": b"\x00\x20\x00\xBE",
                        "memsz": 4,
                        "flags": 5,
                        "align": 1,
                    }
                ],
                entry=FLASH_BASE + 0x101,
            )
        )

        with self.assertRaisesRegex(FirmwareExecutionError, "not in an executable loaded segment"):
            board.run_test_firmware(image)
        self.assertEqual(board.bus.read16(FLASH_BASE + 0x200), 0)

    def test_unmapped_instruction_fetch_reports_address(self):
        board = STM32F411REBoard()
        image = self.make_image([0xE000], base=FLASH_BASE + 512 * 1024 - 2)

        with self.assertRaisesRegex(
            FirmwareExecutionError,
            r"Memory access failed at PC 0x08080002",
        ):
            board.run_test_firmware(image)

    def test_test_mode_does_not_replace_vector_table_reset(self):
        board = STM32F411REBoard()
        board.flash.write32(0, SRAM_BASE + SRAM_SIZE)
        board.flash.write32(4, FLASH_BASE + 0x201)
        image = self.make_image([0x2007, 0xBE00])

        board.run_test_firmware(image)
        self.assertEqual(board.cpu.pc, FLASH_BASE + 0x102)

        board.reset()
        self.assertEqual(board.cpu.pc, FLASH_BASE + 0x200)
        self.assertEqual(board.cpu.sp, SRAM_BASE + SRAM_SIZE)

    @unittest.skipUnless(
        shutil.which("arm-none-eabi-gcc")
        and shutil.which("arm-none-eabi-objdump"),
        "GNU Arm Embedded compiler and objdump are not installed",
    )
    def test_compiled_arm_firmware_runs_and_produces_expected_result(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        source = fixture_dir / "minimal_test_firmware.s"
        linker_script = fixture_dir / "minimal_test_firmware.ld"
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "minimal_test_firmware.elf"
            command = [
                shutil.which("arm-none-eabi-gcc"),
                "-mcpu=cortex-m4",
                "-mthumb",
                "-nostdlib",
                "-nostartfiles",
                "-Wl,--build-id=none",
                f"-Wl,-T,{linker_script}",
                "-o",
                str(output),
                str(source),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            disassembly = subprocess.run(
                [
                    shutil.which("arm-none-eabi-objdump"),
                    "-d",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout

            self.assertIn("2014", disassembly)
            self.assertIn("3016", disassembly)
            self.assertIn("be00", disassembly.lower())
            image = parse_elf32_arm(output.read_bytes())

        board = STM32F411REBoard()
        result = board.run_test_firmware(image, max_instructions=2)
        self.assertEqual(result.entry_point, FLASH_BASE + 0x1001)
        self.assertEqual(result.instructions_executed, 2)
        self.assertEqual(result.registers[0], 42)
        self.assertEqual(board.cpu.pc, FLASH_BASE + 0x1004)

    @unittest.skipUnless(
        shutil.which("arm-none-eabi-gcc")
        and shutil.which("arm-none-eabi-objdump"),
        "GNU Arm Embedded compiler and objdump are not installed",
    )
    def test_compiled_c_uses_flash_and_sram_and_runs_to_expected_result(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        source = fixture_dir / "compiled_c_firmware.c"
        linker_script = fixture_dir / "compiled_c_firmware.ld"
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "compiled_c_firmware.elf"
            command = [
                shutil.which("arm-none-eabi-gcc"),
                "-mcpu=cortex-m4",
                "-mthumb",
                "-Os",
                "-ffreestanding",
                "-fno-builtin",
                "-fno-unwind-tables",
                "-fno-asynchronous-unwind-tables",
                "-nostdlib",
                "-nostartfiles",
                "-Wl,--build-id=none",
                f"-Wl,-T,{linker_script}",
                "-o",
                str(output),
                str(source),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            disassembly = subprocess.run(
                [
                    shutil.which("arm-none-eabi-objdump"),
                    "-d",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertIn("ble", disassembly)
            self.assertIn("bl\t", disassembly)
            self.assertIn("bkpt", disassembly)
            image = parse_elf32_arm(output.read_bytes())

        flash_segments = [
            segment
            for segment in image.segments
            if segment.flags & 1 and segment.virtual_address == FLASH_BASE
        ]
        writable_segments = [
            segment
            for segment in image.segments
            if segment.virtual_address == SRAM_BASE
        ]
        self.assertEqual(len(flash_segments), 1)
        self.assertEqual(flash_segments[0].load_address, FLASH_BASE)
        self.assertEqual(len(writable_segments), 1)
        data_segment = writable_segments[0]
        self.assertEqual(data_segment.load_address, FLASH_BASE + 0x44)
        self.assertEqual(data_segment.file_size, 4)
        self.assertEqual(data_segment.memory_size, 12)

        board = STM32F411REBoard()
        board.sram.write32(0, 0xFFFFFFFF)
        board.sram.write32(4, 0xFFFFFFFF)
        result = board.run_test_firmware(image, max_instructions=100)

        self.assertEqual(result.termination, "BKPT #0")
        self.assertEqual(result.registers[0], 13)
        self.assertEqual(board.bus.read32(SRAM_BASE), 7)
        self.assertEqual(board.bus.read32(SRAM_BASE + 4), 13)
        self.assertEqual(board.bus.read32(SRAM_BASE + 8), 0)
        self.assertEqual(board.bus.read32(FLASH_BASE + 0x44), 7)
        self.assertEqual(board.cpu.instructions_executed, 62)
        with self.assertRaises(PermissionError):
            board.bus.write32(FLASH_BASE, 0xFFFFFFFF)


if __name__ == "__main__":
    unittest.main()

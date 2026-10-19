import unittest
from sim.bus import MemoryMap
from sim.cpu import CPU
from sim.memory import Memory


def make_cpu(*instructions: int) -> CPU:
    memory = Memory(size=max(64, len(instructions) * 2))
    for index, instruction in enumerate(instructions):
        memory.write16(index * 2, instruction)
    return CPU(memory=memory)


def encode_bl(offset: int) -> tuple[int, int]:
    if offset & 1 or not -(1 << 24) <= offset < (1 << 24):
        raise ValueError("BL offset must be even and fit the signed 25-bit range")
    encoded = offset & 0x01FFFFFF
    sign = (encoded >> 24) & 1
    i1 = (encoded >> 23) & 1
    i2 = (encoded >> 22) & 1
    j1 = int(not (i1 ^ sign))
    j2 = int(not (i2 ^ sign))
    first = 0xF000 | (sign << 10) | ((encoded >> 12) & 0x03FF)
    second = 0xD000 | (j1 << 13) | (j2 << 11) | ((encoded >> 1) & 0x07FF)
    return first, second


class CPUTests(unittest.TestCase):
    def test_movs_adds(self):
        cpu = make_cpu(0x200A, 0x3014)
        cpu.run(2)
        self.assertEqual(cpu.regs[0], 30)
        self.assertEqual(cpu.pc, 4)
        self.assertEqual(cpu.Z, 0)

    def test_subs_and_cmp_zero(self):
        cpu = make_cpu(0x200A, 0x380A, 0x2800)
        cpu.run(3)
        self.assertEqual(cpu.regs[0], 0)
        self.assertEqual(cpu.Z, 1)
        self.assertEqual(cpu.C, 1)

    def test_subtraction_borrow_flag(self):
        cpu = make_cpu(0x2000, 0x3801)
        cpu.run(2)
        self.assertEqual(cpu.regs[0], 0xFFFFFFFF)
        self.assertEqual(cpu.N, 1)
        self.assertEqual(cpu.C, 0)

    def test_addition_overflow_and_carry(self):
        cpu = CPU(memory=Memory(size=8))
        cpu.regs[0] = 0xFFFFFFFF
        cpu._add_flags(0xFFFFFFFF, 1, 0x00000000)
        self.assertEqual(cpu.C, 1)
        self.assertEqual(cpu.Z, 1)
        self.assertEqual(cpu.V, 0)

    def test_subtraction_overflow_and_negative(self):
        cpu = CPU(memory=Memory(size=8))
        cpu._sub_flags(0x80000000, 1, 0x7FFFFFFF)
        self.assertEqual(cpu.C, 1)
        self.assertEqual(cpu.N, 0)
        self.assertEqual(cpu.V, 1)

    def test_cmp_register_exact_encoding_flags_and_no_destination_write(self):
        cases = [
            (0x428A, 7, 7, (0, 1, 1, 0)),
            (0x4288, 0, 1, (1, 0, 0, 0)),
            (0x4288, 0x80000000, 1, (0, 0, 1, 1)),
            (0x4288, 3, 5, (1, 0, 0, 0)),
        ]
        for instruction, left, right, expected_flags in cases:
            with self.subTest(instruction=hex(instruction), left=left, right=right):
                cpu = make_cpu(instruction)
                rn = instruction & 0x7
                rm = (instruction >> 3) & 0x7
                cpu.regs[rn] = left
                cpu.regs[rm] = right
                before = list(cpu.regs)

                cpu.step()

                self.assertEqual(cpu.regs, before)
                self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), expected_flags)
                self.assertEqual(cpu.pc, 2)

    def test_branch_offset_uses_pc_relative_address(self):
        cpu = CPU(memory=Memory(size=64))
        cpu.memory.write16(0x10, 0xE003)
        cpu.pc = 0x10
        cpu.step()
        self.assertEqual(cpu.pc, 0x10 + 4 + 6)

    def test_branch_to_self(self):
        cpu = make_cpu(0xE7FE)
        cpu.step()
        self.assertEqual(cpu.pc, 0)

    def test_conditional_branches_all_conditions_taken_and_not_taken(self):
        cases = [
            (0x0, (0, 1, 0, 0), (0, 0, 0, 0)),  # EQ
            (0x1, (0, 0, 0, 0), (0, 1, 0, 0)),  # NE
            (0x2, (0, 0, 1, 0), (0, 0, 0, 0)),  # CS/HS
            (0x3, (0, 0, 0, 0), (0, 0, 1, 0)),  # CC/LO
            (0x4, (1, 0, 0, 0), (0, 0, 0, 0)),  # MI
            (0x5, (0, 0, 0, 0), (1, 0, 0, 0)),  # PL
            (0x6, (0, 0, 0, 1), (0, 0, 0, 0)),  # VS
            (0x7, (0, 0, 0, 0), (0, 0, 0, 1)),  # VC
            (0x8, (0, 0, 1, 0), (0, 0, 0, 0)),  # HI
            (0x9, (0, 0, 0, 0), (0, 0, 1, 0)),  # LS
            (0xA, (0, 0, 0, 0), (1, 0, 0, 0)),  # GE
            (0xB, (1, 0, 0, 0), (0, 0, 0, 0)),  # LT
            (0xC, (0, 0, 0, 0), (0, 1, 0, 0)),  # GT
            (0xD, (0, 1, 0, 0), (0, 0, 0, 0)),  # LE
        ]
        for condition, taken_flags, not_taken_flags in cases:
            instruction = 0xD000 | (condition << 8) | 3
            with self.subTest(condition=condition, taken=True):
                cpu = make_cpu(instruction)
                cpu.pc = 0x20
                cpu.memory.write16(0x20, instruction)
                cpu.N, cpu.Z, cpu.C, cpu.V = taken_flags

                cpu.step()

                self.assertEqual(cpu.pc, 0x2A)
                self.assertEqual(
                    (cpu.N, cpu.Z, cpu.C, cpu.V), taken_flags
                )
            with self.subTest(condition=condition, taken=False):
                cpu = make_cpu(instruction)
                cpu.pc = 0x20
                cpu.memory.write16(0x20, instruction)
                cpu.N, cpu.Z, cpu.C, cpu.V = not_taken_flags

                cpu.step()

                self.assertEqual(cpu.pc, 0x22)
                self.assertEqual(
                    (cpu.N, cpu.Z, cpu.C, cpu.V), not_taken_flags
                )

    def test_conditional_branch_sign_extension_and_negative_target(self):
        cpu = make_cpu(0xD1FC)  # BNE with imm8=-4; PC-relative target is -4 from address 0
        cpu.Z = 0

        cpu.step()

        self.assertEqual(cpu.pc, 0xFFFFFFFC)

        cpu = CPU(memory=Memory(size=64))
        cpu.memory.write16(0x20, 0xD1FC)
        cpu.pc = 0x20
        cpu.Z = 1

        cpu.step()

        self.assertEqual(cpu.pc, 0x22)

    def test_conditional_branch_rejects_reserved_and_svc_conditions(self):
        for instruction in (0xDE00, 0xDF00):
            with self.subTest(instruction=hex(instruction)):
                cpu = make_cpu(instruction)
                with self.assertRaisesRegex(
                    NotImplementedError, "Unsupported conditional branch condition"
                ):
                    cpu.step()

    def test_bl_forward_and_backward_targets_lr_and_flags(self):
        for address, target in ((0x100, 0x234), (0x200, 0x80)):
            with self.subTest(address=hex(address), target=hex(target)):
                cpu = CPU(memory=Memory(size=0x400))
                first, second = encode_bl(target - (address + 4))
                cpu.memory.write16(address, first)
                cpu.memory.write16(address + 2, second)
                cpu.pc = address
                cpu.lr = 0xDEADBEEF
                cpu.N, cpu.Z, cpu.C, cpu.V = 1, 0, 1, 1

                cpu.step()

                self.assertEqual(cpu.pc, target)
                self.assertEqual(cpu.lr, address + 5)
                self.assertEqual(cpu.instructions_executed, 1)
                self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 0, 1, 1))

    def test_bl_long_signed_offset_reconstruction(self):
        offset = -(1 << 22) - 0x1234
        first, second = encode_bl(offset)
        cpu = CPU(memory=Memory(size=0x400000))
        cpu.memory.write16(0, first)
        cpu.memory.write16(2, second)

        cpu.step()

        self.assertEqual(cpu.pc, (4 + offset) & 0xFFFFFFFF)
        self.assertEqual(cpu.lr, 5)

    def test_bl_encoding_from_compiler_disassembly(self):
        address = 0x0800101E
        cpu = CPU(memory=Memory(size=512 * 1024, base_address=0x08000000))
        cpu.pc = address
        cpu.memory.write16(address, 0xF7FF)
        cpu.memory.write16(address + 2, 0xFFEF)

        cpu.step()

        self.assertEqual(cpu.pc, 0x08001000)
        self.assertEqual(cpu.lr, 0x08001023)
        self.assertEqual(cpu.instructions_executed, 1)

    def test_bl_bx_lr_call_and_return_sequence(self):
        cpu = CPU(memory=Memory(size=64))
        first, second = encode_bl(8)
        cpu.memory.write16(0, first)
        cpu.memory.write16(2, second)
        cpu.memory.write16(4, 0xBE00)
        cpu.memory.write16(12, 0x4770)  # BX lr
        cpu.N, cpu.Z, cpu.C, cpu.V = 1, 1, 0, 1

        cpu.step()
        self.assertEqual(cpu.pc, 12)
        self.assertEqual(cpu.lr, 5)
        self.assertEqual(cpu.instructions_executed, 1)

        cpu.step()
        self.assertEqual(cpu.pc, 4)
        self.assertEqual(cpu.lr, 5)
        self.assertEqual(cpu.instructions_executed, 2)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 1, 0, 1))

    def test_bx_lr_branches_to_thumb_return_address(self):
        cpu = make_cpu(0x4770)
        cpu.lr = 0x12345679

        cpu.step()

        self.assertEqual(cpu.pc, 0x12345678)
        self.assertEqual(cpu.lr, 0x12345679)
        self.assertEqual(cpu.instructions_executed, 1)

    def test_bl_rejects_malformed_suffix_without_partial_state_change(self):
        cpu = CPU(memory=Memory(size=16))
        cpu.pc = 4
        cpu.lr = 0x12345678
        cpu.N, cpu.Z, cpu.C, cpu.V = 1, 0, 1, 0
        cpu.memory.write16(4, 0xF000)
        cpu.memory.write16(6, 0xE000)

        with self.assertRaisesRegex(NotImplementedError, "Unsupported 32-bit"):
            cpu.step()

        self.assertEqual(cpu.pc, 4)
        self.assertEqual(cpu.lr, 0x12345678)
        self.assertEqual(cpu.instructions_executed, 0)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 0, 1, 0))

    def test_bl_second_halfword_boundary_failure_is_atomic(self):
        cpu = CPU(memory=Memory(size=2))
        cpu.lr = 0x12345678
        cpu.memory.write16(0, 0xF000)

        with self.assertRaises(IndexError):
            cpu.step()

        self.assertEqual(cpu.pc, 0)
        self.assertEqual(cpu.lr, 0x12345678)
        self.assertEqual(cpu.instructions_executed, 0)

    def test_movs_high_register_decode_and_flags(self):
        cpu = CPU(memory=Memory(size=32))
        cpu.regs[1] = 0xA5A5A5A5
        cpu.regs[8] = 0x11223344
        cpu.N, cpu.Z, cpu.C, cpu.V = 0, 1, 1, 1
        cpu.memory.write16(0, 0x4688)
        cpu.step()
        self.assertEqual(cpu.regs[8], 0xA5A5A5A5)
        self.assertEqual(cpu.regs[1], 0xA5A5A5A5)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (0, 1, 1, 1))

    def test_movs_high_register_source_and_destination_selection(self):
        cpu = CPU(memory=Memory(size=32))
        cpu.regs[8] = 0x13579BDF
        cpu.memory.write16(0, 0x4641)
        cpu.step()
        self.assertEqual(cpu.regs[1], 0x13579BDF)
        self.assertEqual(cpu.regs[8], 0x13579BDF)

    def test_high_register_mov_preserves_all_flags_and_supports_sp(self):
        cpu = CPU(memory=Memory(size=32))
        cpu.sp = 0x20000100
        cpu.N, cpu.Z, cpu.C, cpu.V = 1, 0, 1, 1
        cpu.memory.write16(0, 0x4668)  # MOV r0, sp

        cpu.step()

        self.assertEqual(cpu.regs[0], 0x20000100)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 0, 1, 1))

    def test_high_register_add_preserves_all_flags_and_supports_sp(self):
        cpu = CPU(memory=Memory(size=32))
        cpu.sp = 0x20000100
        cpu.regs[0] = 0x20
        cpu.N, cpu.Z, cpu.C, cpu.V = 1, 1, 0, 1
        cpu.memory.write16(0, 0x4485)  # ADD sp, r0

        cpu.step()

        self.assertEqual(cpu.sp, 0x20000120)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 1, 0, 1))

    def test_sp_adjust_immediate_exact_encodings_scaling_flags_and_wraparound(self):
        cases = [
            (0xB085, 0x100, 0xEC),
            (0xB003, 0x100, 0x10C),
            (0xB081, 0x00000000, 0xFFFFFFFC),
            (0xB001, 0xFFFFFFFC, 0x00000000),
        ]
        for instruction, initial_sp, expected_sp in cases:
            with self.subTest(instruction=hex(instruction)):
                cpu = make_cpu(instruction)
                cpu.sp = initial_sp
                cpu.N, cpu.Z, cpu.C, cpu.V = 1, 0, 1, 1

                cpu.step()

                self.assertEqual(cpu.sp, expected_sp)
                self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 0, 1, 1))
                self.assertEqual(cpu.pc, 2)
                self.assertEqual(cpu.instructions_executed, 1)

    def test_add_register_sp_immediate_scaling_selection_and_wraparound(self):
        cases = [
            (0xAB03, 0x100, 3, 0x10C),
            (0xA800, 0xFFFFFFFC, 0, 0xFFFFFFFC),
            (0xA9FF, 0xFFFFFFF0, 1, 0x000003EC),
        ]
        for instruction, initial_sp, rd, expected in cases:
            with self.subTest(instruction=hex(instruction)):
                cpu = make_cpu(instruction)
                cpu.sp = initial_sp
                cpu.regs[rd] = 0xDEADBEEF
                cpu.N, cpu.Z, cpu.C, cpu.V = 0, 1, 1, 0

                cpu.step()

                self.assertEqual(cpu.regs[rd], expected)
                self.assertEqual(cpu.sp, initial_sp)
                self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (0, 1, 1, 0))

    def test_sp_relative_word_load_store_exact_encodings_and_flags(self):
        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0x40
        cpu.regs[3] = 0xA1B2C3D4
        cpu.N, cpu.Z, cpu.C, cpu.V = 1, 0, 1, 0
        cpu.memory.write16(0, 0x9305)  # STR r3, [sp, #20]

        cpu.step()

        self.assertEqual(cpu.memory.read32(0x54), 0xA1B2C3D4)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 0, 1, 0))

        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0x40
        cpu.regs[2] = 0xDEADBEEF
        cpu.N, cpu.Z, cpu.C, cpu.V = 0, 1, 0, 1
        cpu.memory.write32(0x7C, 0x12345678)
        cpu.memory.write16(0, 0x9A0F)  # LDR r2, [sp, #60]

        cpu.step()

        self.assertEqual(cpu.regs[2], 0x12345678)
        self.assertEqual(cpu.sp, 0x40)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (0, 1, 0, 1))
        self.assertEqual(cpu.pc, 2)

    def test_sp_relative_word_access_out_of_bounds_is_atomic(self):
        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0xFC
        cpu.regs[0] = 0xAABBCCDD
        cpu.N, cpu.Z, cpu.C, cpu.V = 1, 1, 0, 1
        cpu.memory.write16(0, 0x9001)  # STR r0, [sp, #4]

        with self.assertRaises(IndexError):
            cpu.step()

        self.assertEqual(cpu.sp, 0xFC)
        self.assertEqual(cpu.regs[0], 0xAABBCCDD)
        self.assertEqual(cpu.memory.read32(0xFC), 0)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 1, 0, 1))

        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0xFC
        cpu.regs[1] = 0x55667788
        cpu.N, cpu.Z, cpu.C, cpu.V = 0, 1, 1, 0
        cpu.memory.write16(0, 0x9901)  # LDR r1, [sp, #4]

        with self.assertRaises(IndexError):
            cpu.step()

        self.assertEqual(cpu.sp, 0xFC)
        self.assertEqual(cpu.regs[1], 0x55667788)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (0, 1, 1, 0))

    def test_logical_register_ops_preserve_carry_and_overflow(self):
        for opcode, expected in [
            (0x4008, 0x00000000),
            (0x4048, 0xFFFFFFFF),
            (0x4308, 0xFFFFFFFF),
            (0x4388, 0xF0F0F0F0),
            (0x43C8, 0xF0F0F0F0),
        ]:
            cpu = CPU(memory=Memory(size=32))
            cpu.regs[0] = 0xF0F0F0F0
            cpu.regs[1] = 0x0F0F0F0F
            cpu.C = 1
            cpu.V = 1
            cpu.memory.write16(0, opcode)
            cpu.step()
            self.assertEqual(cpu.regs[0], expected)
            self.assertEqual(cpu.N, (expected >> 31) & 1)
            self.assertEqual(cpu.Z, int(expected == 0))
            self.assertEqual(cpu.C, 1)
            self.assertEqual(cpu.V, 1)

    def test_shift_register_and_immediate_edge_cases(self):
        cpu = CPU(memory=Memory(size=32))
        cpu.regs[0] = 0x80000000
        cpu.regs[1] = 1
        cpu.C = 0
        cpu.memory.write16(0, 0x4088)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0x00000000)
        self.assertEqual(cpu.C, 1)

        cpu = CPU(memory=Memory(size=32))
        cpu.regs[0] = 0x00000001
        cpu.regs[1] = 32
        cpu.C = 0
        cpu.memory.write16(0, 0x40C8)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0)
        self.assertEqual(cpu.C, 0)

        cpu = CPU(memory=Memory(size=32))
        cpu.regs[0] = 0x80000001
        cpu.regs[1] = 16
        cpu.memory.write16(0, 0x4108)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0xFFFF8000)
        self.assertEqual(cpu.C, 0)
        self.assertEqual(cpu.N, 1)
        self.assertEqual(cpu.Z, 0)

        cpu = CPU(memory=Memory(size=32))
        cpu.regs[0] = 0x00000010
        cpu.C = 0
        cpu.memory.write16(0, 0x0800)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0)
        self.assertEqual(cpu.C, 0)

    def test_word_ldr_str_exact_offset_scaling(self):
        cpu = CPU(memory=Memory(size=256))
        cpu.regs[0] = 0x11223344
        cpu.regs[1] = 0x80
        cpu.memory.write16(0, 0x60C8)
        cpu.step()
        self.assertEqual(cpu.memory.read32(0x8C), 0x11223344)

        cpu = CPU(memory=Memory(size=256))
        cpu.regs[1] = 0x80
        cpu.memory.write32(0x8C, 0xA5A5A5A5)
        cpu.pc = 0
        cpu.memory.write16(0, 0x68C8)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0xA5A5A5A5)
        self.assertEqual(cpu.N, 0)
        self.assertEqual(cpu.Z, 0)

    def test_memory_access_immediate_word_round_trip(self):
        cpu = CPU(memory=Memory(size=256))
        cpu.regs[0] = 0x11223344
        cpu.regs[1] = 0x80
        cpu.memory.write16(0, 0x6008)
        cpu.step()
        self.assertEqual(cpu.memory.read32(0x80), 0x11223344)

        cpu = CPU(memory=Memory(size=256))
        cpu.regs[1] = 0x80
        cpu.memory.write32(0x80, 0xA5A5A5A5)
        cpu.memory.write16(0, 0x6808)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0xA5A5A5A5)
        self.assertEqual(cpu.N, 0)
        self.assertEqual(cpu.Z, 0)

    def test_byte_halfword_access_exact_encodings_and_zero_extend(self):
        cpu = CPU(memory=Memory(size=256))
        cpu.regs[1] = 0x80
        cpu.regs[0] = 0x12345678
        cpu.memory.write16(0, 0x7148)
        cpu.step()
        self.assertEqual(cpu.memory.read8(0x85), 0x78)

        cpu = CPU(memory=Memory(size=256))
        cpu.regs[1] = 0x80
        cpu.memory.write8(0x85, 0xFF)
        cpu.memory.write16(0, 0x7948)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0xFF)
        self.assertEqual(cpu.N, 0)
        self.assertEqual(cpu.Z, 0)

        cpu = CPU(memory=Memory(size=256))
        cpu.regs[1] = 0x80
        cpu.regs[0] = 0x12345678
        cpu.memory.write16(0, 0x8148)
        cpu.step()
        self.assertEqual(cpu.memory.read16(0x8A), 0x5678)

        cpu = CPU(memory=Memory(size=256))
        cpu.regs[1] = 0x80
        cpu.memory.write16(0x8A, 0xFFFF)
        cpu.memory.write16(0, 0x8948)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0xFFFF)
        self.assertEqual(cpu.N, 0)
        self.assertEqual(cpu.Z, 0)

        with self.assertRaises(IndexError):
            cpu.memory.read8(0x200)

    def test_all_load_instructions_preserve_condition_flags(self):
        cases = [
            (0x6808, 0x80, 0xA5A5A5A5, 4),
            (0x7808, 0x80, 0xFF, 1),
            (0x8808, 0x80, 0xFFFF, 2),
            (0x4801, 0, 0xFFFFFFFF, 4),
        ]
        for instruction, base, value, width in cases:
            with self.subTest(instruction=hex(instruction)):
                cpu = CPU(memory=Memory(size=256))
                cpu.regs[1] = base
                cpu.N, cpu.Z, cpu.C, cpu.V = 1, 0, 1, 0
                cpu.memory.write16(0, instruction)
                if instruction & 0xF800 == 0x4800:
                    target = 8
                else:
                    target = base
                for byte_index in range(width):
                    cpu.memory.write8(
                        target + byte_index,
                        (value >> (8 * byte_index)) & 0xFF,
                    )

                cpu.step()

                rd = (instruction >> 8) & 0x7 if instruction & 0xF800 == 0x4800 else instruction & 0x7
                self.assertEqual(cpu.regs[rd], value)
                self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 0, 1, 0))

    def test_byte_halfword_and_literal_loads(self):
        cpu = CPU(memory=Memory(size=256))
        cpu.regs[1] = 0x80
        cpu.regs[0] = 0x12345678
        cpu.memory.write16(0, 0x7008)
        cpu.step()
        self.assertEqual(cpu.memory.read8(0x80), 0x78)

        cpu = CPU(memory=Memory(size=256))
        cpu.regs[1] = 0x80
        cpu.memory.write16(0x80, 0x00FF)
        cpu.memory.write16(0, 0x7808)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0xFF)

        cpu = CPU(memory=Memory(size=256))
        cpu.regs[1] = 0x80
        cpu.regs[0] = 0x12345678
        cpu.memory.write16(0, 0x8008)
        cpu.step()
        self.assertEqual(cpu.memory.read16(0x80), 0x5678)

        cpu = CPU(memory=Memory(size=256))
        cpu.regs[1] = 0x80
        cpu.memory.write16(0x80, 0xDEAD)
        cpu.memory.write16(0, 0x8808)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0xDEAD)

        cpu = CPU(memory=Memory(size=256))
        cpu.pc = 0x10
        cpu.memory.write16(0x10, 0x4805)
        cpu.memory.write32(0x10 + 4 + 5 * 4, 0x13579BDF)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0x13579BDF)

    def test_pc_relative_literal_ldr_alignment_offsets_and_pc_update(self):
        cases = [
            (0x10, 0x4800, 0x14, 0x10203040),
            (0x12, 0x4A03, 0x20, 0x55667788),
            (0x1E, 0x4F01, 0x24, 0xA1B2C3D4),
        ]
        for instruction_address, instruction, target, expected in cases:
            with self.subTest(instruction_address=instruction_address):
                cpu = CPU(memory=Memory(size=0x200))
                cpu.pc = instruction_address
                cpu.regs[0] = 0xDEADBEEF
                cpu.regs[1] = 0xCAFEBABE
                cpu.N = 1
                cpu.Z = 1
                cpu.C = 1
                cpu.V = 1
                cpu.memory.write16(instruction_address, instruction)
                cpu.memory.write8(target, expected & 0xFF)
                cpu.memory.write8(target + 1, (expected >> 8) & 0xFF)
                cpu.memory.write8(target + 2, (expected >> 16) & 0xFF)
                cpu.memory.write8(target + 3, (expected >> 24) & 0xFF)

                cpu.step()

                rd = (instruction >> 8) & 0x7
                self.assertEqual(cpu.regs[rd], expected)
                for register in range(8):
                    if register != rd:
                        self.assertEqual(
                            cpu.regs[register],
                            0xDEADBEEF if register == 0 else 0xCAFEBABE if register == 1 else 0,
                        )
                self.assertEqual(cpu.pc, instruction_address + 2)
                self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 1, 1, 1))

    def test_pc_relative_literal_ldr_out_of_bounds(self):
        cpu = CPU(memory=Memory(size=0x100))
        cpu.pc = 0xFC
        cpu.memory.write16(0xFC, 0x4800)
        with self.assertRaises(IndexError):
            cpu.step()

    def test_push_pop_stack_ops_and_optional_lr_pc(self):
        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0x100
        cpu.N, cpu.Z, cpu.C, cpu.V = 1, 0, 1, 0
        cpu.regs[0] = 0x11
        cpu.regs[1] = 0x22
        cpu.memory.write16(0, 0xB403)
        cpu.step()
        self.assertEqual(cpu.sp, 0xF8)
        self.assertEqual(cpu.memory.read32(0xF8), 0x11)
        self.assertEqual(cpu.memory.read32(0xFC), 0x22)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 0, 1, 0))

        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0xF8
        cpu.N, cpu.Z, cpu.C, cpu.V = 0, 1, 0, 1
        cpu.memory.write32(0xF8, 0x11)
        cpu.memory.write32(0xFC, 0x22)
        cpu.memory.write16(0, 0xBC03)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0x11)
        self.assertEqual(cpu.regs[1], 0x22)
        self.assertEqual(cpu.sp, 0x100)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (0, 1, 0, 1))

        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0x100
        cpu.N, cpu.Z, cpu.C, cpu.V = 1, 1, 0, 1
        cpu.regs[0] = 0x11
        cpu.lr = 0xABCDEF01
        cpu.memory.write16(0, 0xB501)
        cpu.step()
        self.assertEqual(cpu.sp, 0xF8)
        self.assertEqual(cpu.memory.read32(0xF8), 0x11)
        self.assertEqual(cpu.memory.read32(0xFC), 0xABCDEF01)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 1, 0, 1))

        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0xF8
        cpu.N, cpu.Z, cpu.C, cpu.V = 1, 0, 0, 1
        cpu.memory.write32(0xF8, 0x11)
        cpu.memory.write32(0xFC, 0x2001)
        cpu.memory.write16(0, 0xBD01)
        cpu.step()
        self.assertEqual(cpu.regs[0], 0x11)
        self.assertEqual(cpu.pc, 0x2000)
        self.assertEqual(cpu.sp, 0x100)
        self.assertEqual((cpu.N, cpu.Z, cpu.C, cpu.V), (1, 0, 0, 1))

    def test_push_pop_single_register_and_invalid_cases(self):
        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0x80
        cpu.regs[7] = 0xFEDCBA98
        cpu.memory.write16(0, 0xB480)
        cpu.step()
        self.assertEqual(cpu.sp, 0x7C)
        self.assertEqual(cpu.memory.read32(0x7C), 0xFEDCBA98)

        cpu.regs[7] = 0
        cpu.memory.write16(2, 0xBC80)
        cpu.step()
        self.assertEqual(cpu.regs[7], 0xFEDCBA98)
        self.assertEqual(cpu.sp, 0x80)

        for instruction in (0xB400, 0xBC00):
            with self.subTest(empty_list_instruction=hex(instruction)):
                invalid = CPU(memory=Memory(size=256))
                invalid.sp = 0x80
                invalid.memory.write16(0, instruction)
                with self.assertRaises(NotImplementedError):
                    invalid.step()
                self.assertEqual(invalid.sp, 0x80)

        invalid = CPU(memory=Memory(size=256))
        invalid.memory.write16(0, 0xB200)
        with self.assertRaises(NotImplementedError):
            invalid.step()

    def test_push_pop_out_of_bounds_and_invalid_pc_target(self):
        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0x102
        cpu.regs[0] = 0x12345678
        cpu.memory.write16(0, 0xB401)
        with self.assertRaises(IndexError):
            cpu.step()
        self.assertEqual(cpu.sp, 0x102)

        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0xFD
        cpu.regs[0] = 0xAAAAAAAA
        cpu.memory.write16(0, 0xBC01)
        with self.assertRaises(IndexError):
            cpu.step()
        self.assertEqual(cpu.regs[0], 0xAAAAAAAA)
        self.assertEqual(cpu.sp, 0xFD)

        cpu = CPU(memory=Memory(size=256))
        cpu.sp = 0xF8
        cpu.regs[0] = 0xAAAAAAAA
        cpu.memory.write32(0xF8, 0xBBBBBBBB)
        cpu.memory.write32(0xFC, 0x2000)
        cpu.memory.write16(0, 0xBD01)
        with self.assertRaises(NotImplementedError):
            cpu.step()
        self.assertEqual(cpu.regs[0], 0xAAAAAAAA)
        self.assertEqual(cpu.sp, 0xF8)

    def test_cpu_load_store_and_stack_instructions_use_mapped_bus(self):
        code = Memory(size=32)
        ram = Memory(size=256)
        memory_map = MemoryMap()
        memory_map.map_region(0, 32, code)
        memory_map.map_region(0x100, 256, ram)

        instructions = [
            0x6008,  # STR R0, [R1]
            0x6808,  # LDR R0, [R1]
            0x7048,  # STRB R0, [R1, #1]
            0x7848,  # LDRB R0, [R1, #1]
            0x8048,  # STRH R0, [R1, #2]
            0x8848,  # LDRH R0, [R1, #2]
            0xB401,  # PUSH {R0}
            0xBC01,  # POP {R0}
            0x4800,  # LDR R0, [PC, #0]
        ]
        for index, instruction in enumerate(instructions):
            code.write16(index * 2, instruction)
        code.write32(0x14, 0x89ABCDEF)

        cpu = CPU(memory=memory_map)
        cpu.regs[0] = 0x12345678
        cpu.regs[1] = 0x100
        cpu.sp = 0x180
        cpu.run(len(instructions))

        self.assertEqual(ram.read32(0), 0x00787878)
        self.assertEqual(ram.read8(1), 0x78)
        self.assertEqual(ram.read16(2), 0x0078)
        self.assertEqual(cpu.regs[0], 0x89ABCDEF)
        self.assertEqual(cpu.sp, 0x180)
        self.assertEqual(ram.read32(0x7C), 0x78)

    def test_push_prevalidates_all_mapped_writes(self):
        code = Memory(size=4)
        first_stack_region = Memory(size=4)
        second_stack_region = Memory(size=4)
        first_stack_region.write32(0, 0x11111111)
        second_stack_region.write32(0, 0x22222222)
        memory_map = MemoryMap()
        memory_map.map_region(0, 4, code)
        memory_map.map_region(0x100, 4, first_stack_region)
        memory_map.map_region(0x104, 4, second_stack_region, writable=False)
        code.write16(0, 0xB403)

        cpu = CPU(memory=memory_map)
        cpu.sp = 0x108
        cpu.regs[0] = 0xAAAAAAAA
        cpu.regs[1] = 0xBBBBBBBB
        with self.assertRaises(PermissionError):
            cpu.step()

        self.assertEqual(cpu.sp, 0x108)
        self.assertEqual(first_stack_region.read32(0), 0x11111111)

    def test_unsupported_instruction_raises(self):
        cpu = make_cpu(0xFFFF)
        with self.assertRaises(NotImplementedError):
            cpu.step()


if __name__ == "__main__":
    unittest.main()

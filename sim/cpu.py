from __future__ import annotations

from dataclasses import dataclass
from .bus import MemoryBus

MASK32 = 0xFFFFFFFF


@dataclass
class CPU:
    """Educational subset of a Thumb CPU; not a complete Cortex-M implementation."""

    memory: MemoryBus
    pc: int = 0

    def __post_init__(self) -> None:
        self.regs = [0] * 16
        self.N = 0
        self.Z = 0
        self.C = 0
        self.V = 0
        self.halted = False
        self.instructions_executed = 0

    def reset(self, *, pc: int = 0, sp: int = 0) -> None:
        self.regs = [0] * 16
        self.regs[13] = self._u32(sp)
        self.pc = self._u32(pc)
        self.N = 0
        self.Z = 0
        self.C = 0
        self.V = 0
        self.halted = False
        self.instructions_executed = 0

    @staticmethod
    def _u32(value: int) -> int:
        return int(value) & MASK32

    @property
    def sp(self) -> int:
        return self.regs[13]

    @sp.setter
    def sp(self, value: int) -> None:
        self.regs[13] = self._u32(value)

    @property
    def lr(self) -> int:
        return self.regs[14]

    @lr.setter
    def lr(self, value: int) -> None:
        self.regs[14] = self._u32(value)

    def _set_nz(self, result: int) -> None:
        result = self._u32(result)
        self.N = (result >> 31) & 1
        self.Z = int(result == 0)

    def _add_flags(self, a: int, b: int, result: int) -> None:
        a = self._u32(a)
        b = self._u32(b)
        result = self._u32(result)
        unsigned_sum = a + b
        self.C = int(unsigned_sum > MASK32)
        sign_a = (a >> 31) & 1
        sign_b = (b >> 31) & 1
        sign_r = (result >> 31) & 1
        self.V = int((sign_a == sign_b) and (sign_r != sign_a))
        self._set_nz(result)

    def _sub_flags(self, a: int, b: int, result: int) -> None:
        a = self._u32(a)
        b = self._u32(b)
        result = self._u32(result)
        self.C = int(a >= b)
        sign_a = (a >> 31) & 1
        sign_b = (b >> 31) & 1
        sign_r = (result >> 31) & 1
        self.V = int((sign_a != sign_b) and (sign_r != sign_a))
        self._set_nz(result)

    def _condition_passed(self, condition: int) -> bool:
        conditions = (
            bool(self.Z),
            not self.Z,
            bool(self.C),
            not self.C,
            bool(self.N),
            not self.N,
            bool(self.V),
            not self.V,
            bool(self.C and not self.Z),
            bool(not self.C or self.Z),
            self.N == self.V,
            self.N != self.V,
            bool(not self.Z and self.N == self.V),
            bool(self.Z or self.N != self.V),
        )
        if not 0 <= condition < len(conditions):
            raise NotImplementedError(
                f"Unsupported conditional branch condition 0x{condition:X}"
            )
        return conditions[condition]

    @staticmethod
    def _s32(value: int) -> int:
        value = value & MASK32
        return (value ^ 0x80000000) - 0x80000000

    @staticmethod
    def _decode_high_register(instruction: int) -> int:
        return (instruction & 0x7) | (((instruction >> 7) & 1) << 3)

    def _shift_left_imm(self, value: int, count: int) -> tuple[int, int]:
        value = self._u32(value)
        if count == 0:
            return value, self.C
        if count < 32:
            return (value << count) & MASK32, (value >> (32 - count)) & 1
        if count >= 32:
            return 0, (value >> 31) & 1
        return 0, 0

    def _shift_right_logical(self, value: int, count: int) -> tuple[int, int]:
        value = self._u32(value)
        if count == 0:
            return value, self.C
        if count < 32:
            return value >> count, (value >> (count - 1)) & 1
        if count >= 32:
            return 0, (value >> 31) & 1
        return 0, 0

    def _shift_right_arithmetic(self, value: int, count: int) -> tuple[int, int]:
        value = self._u32(value)
        if count == 0:
            return value, self.C
        if count < 32:
            shifted = self._s32(value) >> count
            return self._u32(shifted), (value >> (count - 1)) & 1
        if count >= 32:
            if value & 0x80000000:
                return MASK32, 1
            return 0, 0
        return 0, 0

    def step(self) -> None:
        if self.halted:
            return

        address = self.pc
        instruction = self.memory.read16(address)

        # BL (Thumb-2): 11110 S imm10 / 11 J1 1 J2 imm11.
        if instruction & 0xF800 == 0xF000:
            second_halfword = self.memory.read16((address + 2) & MASK32)
            if second_halfword & 0xD000 != 0xD000:
                raise NotImplementedError(
                    f"Unsupported 32-bit Thumb instruction "
                    f"0x{instruction:04X} 0x{second_halfword:04X} "
                    f"at 0x{address:08X}"
                )

            sign = (instruction >> 10) & 1
            j1 = (second_halfword >> 13) & 1
            j2 = (second_halfword >> 11) & 1
            i1 = int(not (j1 ^ sign))
            i2 = int(not (j2 ^ sign))
            immediate = (
                (sign << 24)
                | (i1 << 23)
                | (i2 << 22)
                | ((instruction & 0x03FF) << 12)
                | ((second_halfword & 0x07FF) << 1)
            )
            if sign:
                immediate -= 1 << 25

            self.lr = (address + 4) | 1
            self.pc = (address + 4 + immediate) & MASK32
            self.instructions_executed += 1
            return

        self.pc = (self.pc + 2) & MASK32
        self.instructions_executed += 1

        # MOVS Rd, #imm8
        if instruction & 0xF800 == 0x2000:
            rd = (instruction >> 8) & 0x7
            imm8 = instruction & 0xFF
            self.regs[rd] = self._u32(imm8)
            self._set_nz(self.regs[rd])
            return

        # CMP Rn, #imm8
        if instruction & 0xF800 == 0x2800:
            rn = (instruction >> 8) & 0x7
            imm8 = self._u32(instruction & 0xFF)
            a = self._u32(self.regs[rn])
            result = (a - imm8) & MASK32
            self._sub_flags(a, imm8, result)
            return

        # CMP Rn, Rm (low registers)
        if instruction & 0xFFC0 == 0x4280:
            rm = (instruction >> 3) & 0x7
            rn = instruction & 0x7
            a = self._u32(self.regs[rn])
            b = self._u32(self.regs[rm])
            self._sub_flags(a, b, (a - b) & MASK32)
            return

        # ADDS Rd, #imm8
        if instruction & 0xF800 == 0x3000:
            rd = (instruction >> 8) & 0x7
            imm8 = self._u32(instruction & 0xFF)
            a = self._u32(self.regs[rd])
            result = (a + imm8) & MASK32
            self.regs[rd] = result
            self._add_flags(a, imm8, result)
            return

        # SUBS Rd, #imm8
        if instruction & 0xF800 == 0x3800:
            rd = (instruction >> 8) & 0x7
            imm8 = self._u32(instruction & 0xFF)
            a = self._u32(self.regs[rd])
            result = (a - imm8) & MASK32
            self.regs[rd] = result
            self._sub_flags(a, imm8, result)
            return

        # ADD Rd, Rn (low-register, 3-bit form)
        if instruction & 0xF800 == 0x1800:
            rn = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            a = self._u32(self.regs[rd])
            b = self._u32(self.regs[rn])
            result = (a + b) & MASK32
            self.regs[rd] = result
            self._add_flags(a, b, result)
            return

        # SUB Rd, Rn (low-register, 3-bit form)
        if instruction & 0xF800 == 0x1A00:
            rn = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            a = self._u32(self.regs[rd])
            b = self._u32(self.regs[rn])
            result = (a - b) & MASK32
            self.regs[rd] = result
            self._sub_flags(a, b, result)
            return

        # MOVS Rd, Rm
        if instruction & 0xFF00 == 0x4600:
            rm = (instruction >> 3) & 0xF
            rd = self._decode_high_register(instruction)
            value = self._u32(self.regs[rm])
            self.regs[rd] = value
            return

        # ADD Rd, Rm (high-register form)
        if instruction & 0xFE00 == 0x4400:
            rm = (instruction >> 3) & 0xF
            rd = self._decode_high_register(instruction)
            a = self._u32(self.regs[rd])
            b = self._u32(self.regs[rm])
            result = (a + b) & MASK32
            self.regs[rd] = result
            return

        # ADD Rd, SP, #imm8 (word-scaled)
        if instruction & 0xF800 == 0xA800:
            rd = (instruction >> 8) & 0x7
            imm8 = instruction & 0xFF
            self.regs[rd] = (self.sp + (imm8 << 2)) & MASK32
            return

        # ADD/SUB SP, #imm7 (word-scaled)
        if instruction & 0xFF80 in (0xB000, 0xB080):
            imm7 = instruction & 0x7F
            offset = imm7 << 2
            if instruction & 0x0080:
                self.sp = (self.sp - offset) & MASK32
            else:
                self.sp = (self.sp + offset) & MASK32
            return

        # STR Rt, [SP, #imm8] (word-scaled)
        if instruction & 0xF800 == 0x9000:
            rt = (instruction >> 8) & 0x7
            imm8 = instruction & 0xFF
            address = (self.sp + (imm8 << 2)) & MASK32
            self.memory.write32(address, self.regs[rt])
            return

        # LDR Rt, [SP, #imm8] (word-scaled)
        if instruction & 0xF800 == 0x9800:
            rt = (instruction >> 8) & 0x7
            imm8 = instruction & 0xFF
            address = (self.sp + (imm8 << 2)) & MASK32
            self.regs[rt] = self.memory.read32(address)
            return

        # LSLS Rd, Rs
        if instruction & 0xFFC0 == 0x4080:
            rm = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            count = self._u32(self.regs[rm])
            result, carry = self._shift_left_imm(self.regs[rd], count & 0xFF)
            self.regs[rd] = result
            self.C = carry
            self._set_nz(result)
            return

        # LSRS Rd, Rs
        if instruction & 0xFFC0 == 0x40C0:
            rm = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            count = self._u32(self.regs[rm]) & 0xFF
            result, carry = self._shift_right_logical(self.regs[rd], count)
            self.regs[rd] = result
            self.C = carry
            self._set_nz(result)
            return

        # ASRS Rd, Rs
        if instruction & 0xFFC0 == 0x4100:
            rm = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            count = self._u32(self.regs[rm]) & 0xFF
            result, carry = self._shift_right_arithmetic(self.regs[rd], count)
            self.regs[rd] = result
            self.C = carry
            self._set_nz(result)
            return

        # ANDS Rd, Rm
        if instruction & 0xFFC0 == 0x4000:
            rm = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            result = self._u32(self.regs[rd]) & self._u32(self.regs[rm])
            self.regs[rd] = result
            self._set_nz(result)
            return

        # EORS Rd, Rm
        if instruction & 0xFFC0 == 0x4040:
            rm = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            result = self._u32(self.regs[rd]) ^ self._u32(self.regs[rm])
            self.regs[rd] = result
            self._set_nz(result)
            return

        # ORRS Rd, Rm
        if instruction & 0xFFC0 == 0x4300:
            rm = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            result = self._u32(self.regs[rd]) | self._u32(self.regs[rm])
            self.regs[rd] = result
            self._set_nz(result)
            return

        # BICS Rd, Rm
        if instruction & 0xFFC0 == 0x4380:
            rm = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            result = self._u32(self.regs[rd]) & ~self._u32(self.regs[rm])
            self.regs[rd] = result
            self._set_nz(result)
            return

        # MVNS Rd, Rm
        if instruction & 0xFFC0 == 0x43C0:
            rm = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            result = (~self._u32(self.regs[rm])) & MASK32
            self.regs[rd] = result
            self._set_nz(result)
            return

        # STR Rd, [Rb, #imm] : word, immediate offset
        if instruction & 0xF800 == 0x6000:
            imm5 = (instruction >> 6) & 0x1F
            rb = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            address = (self._u32(self.regs[rb]) + (imm5 << 2)) & MASK32
            self.memory.write32(address, self.regs[rd])
            return

        # LDR Rd, [Rb, #imm] : word, immediate offset
        if instruction & 0xF800 == 0x6800:
            imm5 = (instruction >> 6) & 0x1F
            rb = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            address = (self._u32(self.regs[rb]) + (imm5 << 2)) & MASK32
            self.regs[rd] = self.memory.read32(address)
            return

        # STRB Rd, [Rb, #imm]
        if instruction & 0xF800 == 0x7000:
            imm5 = (instruction >> 6) & 0x1F
            rb = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            address = (self._u32(self.regs[rb]) + imm5) & MASK32
            self.memory.write8(address, self.regs[rd] & 0xFF)
            return

        # LDRB Rd, [Rb, #imm]
        if instruction & 0xF800 == 0x7800:
            imm5 = (instruction >> 6) & 0x1F
            rb = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            address = (self._u32(self.regs[rb]) + imm5) & MASK32
            self.regs[rd] = self.memory.read8(address)
            return

        # STRH Rd, [Rb, #imm]
        if instruction & 0xF800 == 0x8000:
            imm5 = (instruction >> 6) & 0x1F
            rb = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            address = (self._u32(self.regs[rb]) + (imm5 << 1)) & MASK32
            self.memory.write16(address, self.regs[rd] & 0xFFFF)
            return

        # LDRH Rd, [Rb, #imm]
        if instruction & 0xF800 == 0x8800:
            imm5 = (instruction >> 6) & 0x1F
            rb = (instruction >> 3) & 0x7
            rd = instruction & 0x7
            address = (self._u32(self.regs[rb]) + (imm5 << 1)) & MASK32
            self.regs[rd] = self.memory.read16(address)
            return

        # LDR Rd, [PC, #imm] : literal form
        if instruction & 0xF800 == 0x4800:
            rd = (instruction >> 8) & 0x7
            imm8 = instruction & 0xFF
            address = ((address + 4) & ~0x3) + (imm8 << 2)
            self.regs[rd] = self.memory.read32(address & MASK32)
            return

        # PUSH {Rlist [, LR]}
        if instruction & 0xFE00 == 0xB400:
            regs = [index for index in range(8) if (instruction & 0xFF) & (1 << index)]
            if instruction & 0x0100:
                regs.append(14)
            if not regs:
                raise NotImplementedError("PUSH with an empty register list is unsupported")
            new_sp = (self.sp - len(regs) * 4) & MASK32
            addresses = [
                (new_sp + index * 4) & MASK32 for index in range(len(regs))
            ]
            for stack_address in addresses:
                self.memory.validate_access(stack_address, 4, write=True)
            for stack_address, reg in zip(addresses, regs):
                self.memory.write32(stack_address, self.regs[reg])
            self.sp = new_sp
            return

        # POP {Rlist [, PC]}
        if instruction & 0xFE00 == 0xBC00:
            regs = [index for index in range(8) if (instruction & 0xFF) & (1 << index)]
            if instruction & 0x0100:
                regs.append(15)
            if not regs:
                raise NotImplementedError("POP with an empty register list is unsupported")
            values = [
                self.memory.read32((self.sp + index * 4) & MASK32)
                for index in range(len(regs))
            ]
            if instruction & 0x0100 and (values[-1] & 1) == 0:
                raise NotImplementedError("ARM-state POP targets are not implemented")
            for reg, value in zip(regs, values):
                if reg != 15:
                    self.regs[reg] = value
            self.sp = (self.sp + len(regs) * 4) & MASK32
            if instruction & 0x0100:
                self.pc = self._u32(values[-1] & ~1)
            return

        # LSL immediate
        if instruction & 0xF800 == 0x0000:
            rd = instruction & 0x7
            imm5 = (instruction >> 6) & 0x1F
            value = self._u32(self.regs[rd])
            result, carry = self._shift_left_imm(value, imm5)
            self.regs[rd] = result
            self.C = carry
            self._set_nz(result)
            return

        # LSR immediate
        if instruction & 0xF800 == 0x0800:
            rd = instruction & 0x7
            imm5 = (instruction >> 6) & 0x1F
            if imm5 == 0:
                imm5 = 32
            value = self._u32(self.regs[rd])
            result, carry = self._shift_right_logical(value, imm5)
            self.regs[rd] = result
            self.C = carry
            self._set_nz(result)
            return

        # ASR immediate
        if instruction & 0xF800 == 0x1000:
            rd = instruction & 0x7
            imm5 = (instruction >> 6) & 0x1F
            if imm5 == 0:
                imm5 = 32
            value = self._u32(self.regs[rd])
            result, carry = self._shift_right_arithmetic(value, imm5)
            self.regs[rd] = result
            self.C = carry
            self._set_nz(result)
            return

        # Unconditional short branch B label
        if instruction & 0xF800 == 0xE000:
            imm11 = instruction & 0x7FF
            if imm11 & 0x400:
                imm11 -= 0x800
            self.pc = (address + 4 + (imm11 << 1)) & MASK32
            return

        # Conditional branch B<cond> label; condition 0xE is reserved and
        # condition 0xF encodes SVC rather than a conditional branch.
        if instruction & 0xF000 == 0xD000:
            condition = (instruction >> 8) & 0xF
            if condition >= 0xE:
                raise NotImplementedError(
                    f"Unsupported conditional branch condition 0x{condition:X} "
                    f"in instruction 0x{instruction:04X}"
                )
            imm8 = instruction & 0xFF
            if imm8 & 0x80:
                imm8 -= 0x100
            if self._condition_passed(condition):
                self.pc = (address + 4 + (imm8 << 1)) & MASK32
            return

        # BX Rm, Thumb targets only in this subset
        if instruction & 0xFF87 == 0x4700:
            rm = (instruction >> 3) & 0xF
            target = self._u32(self.regs[rm])
            if (target & 1) == 0:
                raise NotImplementedError("ARM-state BX targets are not implemented")
            self.pc = self._u32(target & ~1)
            return

        raise NotImplementedError(
            f"Unsupported 16-bit instruction 0x{instruction:04X} at 0x{address:08X}"
        )

    def run(self, max_instructions: int = 1000) -> int:
        if max_instructions < 0:
            raise ValueError("max_instructions must be non-negative")
        before = self.instructions_executed
        for _ in range(max_instructions):
            self.step()
        return self.instructions_executed - before

from sim.cpu import CPU
from sim.memory import Memory


def main() -> None:
    # MOVS r0, #10; ADDS r0, #20; SUBS r1, #3; CMP r0, #30
    program = [0x200A, 0x3014, 0x3903, 0x281E, 0xE7FE]
    memory = Memory(size=256)
    for index, instruction in enumerate(program):
        memory.write16(index * 2, instruction)

    cpu = CPU(memory=memory)
    cpu.run(max_instructions=4)

    print("Milestone 1 CPU demo")
    print(f"R0 = {cpu.regs[0]}")
    print(f"R1 = 0x{cpu.regs[1]:08X}")
    print(f"N={cpu.N} Z={cpu.Z} C={cpu.C} V={cpu.V}")
    print(f"PC = 0x{cpu.pc:08X}")
    print("Expected: R0=30, R1=0xFFFFFFFD, Z=1 after CMP")

if __name__ == "__main__":
    main()

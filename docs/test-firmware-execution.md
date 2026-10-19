# Test-only compiled firmware execution

`STM32F411REBoard.run_test_firmware(image, max_instructions=...)` is a bounded
test harness, not STM32 boot behavior:

1. It accepts a parsed ELF image and loads segments through
   `load_firmware()`.
2. It requires an odd ELF entry point (Thumb-state marker), aligns bit 0 off
   for the emulator PC, and initializes SP to `SRAM_BASE + SRAM_SIZE`.
3. It resets CPU registers and flags, but does not call `board.reset()`, read
   the vector table, clear SRAM, or reset peripherals. Segment BSS tails are
   initialized by the loader; other memory retains its existing contents.
4. It stops when the next halfword at PC is exactly `BKPT #0` (`0xBE00`).
   The marker is observed by the harness and is not executed or counted.
5. Unsupported instructions, unmapped/denied accesses, and instruction-budget
   exhaustion raise `FirmwareExecutionError` with PC and, when available,
   instruction encoding.

The checked-in assembly fixture uses only `MOVS Rd, #imm8` and `ADDS Rd, #imm8`
before the test-only breakpoint. Reproduce the build from the repository root:

```powershell
arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb -nostdlib -nostartfiles `
  '-Wl,--build-id=none' '-Wl,-T,tests/fixtures/minimal_test_firmware.ld' `
  -o minimal_test_firmware.elf tests/fixtures/minimal_test_firmware.s
arm-none-eabi-objdump -d minimal_test_firmware.elf
```

The compiled C compatibility fixture is [compiled_c_firmware.c](../tests/fixtures/compiled_c_firmware.c)
with [compiled_c_firmware.ld](../tests/fixtures/compiled_c_firmware.ld). Its
linker script places executable/read-only content in Flash and gives writable
data a Flash load address and SRAM runtime address. The loader writes the
initial bytes at the load address, copies them to SRAM, and zero-fills the BSS
tail there. The test poisons SRAM before loading and verifies the initialized
global, zero-initialized global, and computed result.

The loader follows the subset contract in
[the ELF parser documentation](elf32-arm-subset.md); overlapping or ambiguous
segment writes are rejected. No startup code, vector-table reset, C runtime,
exception handling, or general ELF execution support is implied.

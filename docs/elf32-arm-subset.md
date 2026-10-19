# ELF32 ARM parser subset

The parser in `sim.elf` is a dependency-free ELF32 little-endian ARM executable
(`ET_EXEC`, `EM_ARM`) reader. It validates the identification/header fields,
program-header table bounds, PT_LOAD file/memory sizes, file-backed data ranges,
32-bit address arithmetic, and `p_align` congruence. The ELF entry must lie in
an executable PT_LOAD segment. Dynamic/interpreter files are rejected.

PT_LOAD file bytes are returned with both virtual and physical addresses
preserved. In this subset `p_paddr` identifies the load address when nonzero
(otherwise `p_vaddr` is the load address), and `p_vaddr` is the runtime address.
If these addresses are equal, file bytes and the zero-filled
`p_memsz - p_filesz` tail are written once at that address. If they differ,
the file bytes are written at the load address and copied to the runtime
address, and the runtime tail is zero-filled there. This models initialized
data stored in Flash but used in SRAM as well as the BSS portion of a combined
PT_LOAD. It does not perform CPU startup copying.

`STM32F411REBoard.load_firmware(image)` validates all source and runtime ranges
through loader-enabled `MemoryMap` permissions before writing any bytes. It
rejects overlapping planned load/runtime writes rather than applying
ambiguous segment ordering. The Flash mapping explicitly allows image loading
while denying ordinary CPU stores. Peripheral mappings are not loader-writable.
No CPU register, PC, or reset state is changed, and the ELF entry point is
returned as metadata only.

The compiled C fixture uses a separate Flash executable segment and a writable
segment with `p_vaddr` in SRAM and `p_paddr` in Flash. Its initialized global is
copied to SRAM and its BSS tail is zeroed through the loader. Firmware using
other ELF layouts, including conflicting/overlapping segments, remains
unsupported.

Explicitly calling `board.reset()` afterward still uses the Cortex-M vector
table and clears SRAM according to the board model; the ELF entry is not a
reset vector. Loader validation occurs for every segment before any segment is
written. Non-loadable metadata program headers are ignored.

No third-party ELF library is required. The local toolchain includes GNU Arm
Embedded GCC 14.3.1 targeting `arm-none-eabi`. The separate, bounded test-only
execution contract is documented in [test firmware execution](test-firmware-execution.md);
it is not a Cortex-M reset or general firmware execution implementation.

# STM32F411RE board memory configuration

## Hardware basis

This board model targets the STM32F411RE (STM32F411xE). ST's product page
identifies the RE device as having 512 KB of Flash and describes the xC/xE
family as having 128 KB of SRAM. The RM0383 memory map places embedded Flash at
`0x08000000` and SRAM at `0x20000000`.

Sources:

- [STM32F411RE product page and datasheet](https://www.st.com/en/microcontrollers-microprocessors/stm32f411re.html)
- [RM0383 reference manual, DM00119316](https://www.st.com/resource/en/reference_manual/dm00119316.pdf), memory organization and memory map

## Mapped regions

| Region | Base | Size | Access |
|---|---:|---:|---|
| Flash | `0x08000000` | 512 KiB | Readable; writes through the CPU bus rejected |
| SRAM | `0x20000000` | 128 KiB | Readable and writable |
| GPIOA register window | `0x40020000` | 1 KiB | Partial GPIOA register model |
| RCC register window | `0x40023800` | 1 KiB | Partial RCC GPIOA clock model |

The system-memory boot ROM (at `0x1FFF0000` in the reference memory map),
other peripheral addresses, and Cortex-M system control space (starting at
`0xE0000000`) are intentionally unmapped. GPIOA/RCC register details and
limitations are listed in [the GPIOA/RCC subset](./stm32f411re-gpioa.md). This
model does not implement boot-mode aliases or system-control registers.

## Reset behavior and assumptions

Call `board.reset()` after setting the vector table in `board.flash`. It reads
the initial Main Stack Pointer from `0x08000000` and the reset vector from
`0x08000004`; the reset vector must have bit 0 set to indicate Thumb state.
The CPU starts at the reset vector with bit 0 cleared in its internal PC and
the initial stack pointer loaded into SP. Other modeled CPU registers, flags,
halt state, and instruction count are reset to zero/initial state.

For deterministic tests, reset clears SRAM and resets modeled GPIOA/RCC state
while retaining Flash, matching the
model's chosen reset policy; it does not emulate power-on SRAM uncertainty or
Flash programming. The `flash` backing object is exposed for model/test
initialization, while normal bus writes to its mapped address range are
rejected. No startup code or firmware loader is provided.

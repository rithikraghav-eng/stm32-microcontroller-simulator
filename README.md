# Microcontroller Simulator

A small, testable Python CPU-emulator foundation. This is an educational ARM Thumb subset, not a complete Cortex-M4 emulator.

## Requirements
- Python 3.10+
- No third-party packages required

## Run
```bash
python -m unittest discover -s tests -v
python main.py
```

## Included 16-bit Thumb instructions
- MOVS Rd, #imm8
- ADDS Rd, #imm8
- SUBS Rd, #imm8
- CMP Rn, #imm8
- Unconditional short B
- BX Rm (Thumb-state targets only)

## Limitations
The optional STM32F411RE board provides Flash/SRAM and a limited GPIOA/RCC model. A strict ELF32 little-endian ARM parser, validated segment loader, and bounded BKPT-terminated test execution mode are available; test execution is not STM32 boot behavior. No startup sequence, NVIC, exceptions, SysTick, other peripheral registers, or complete ARMv7-M / Thumb-2 implementation is provided. See [the board configuration](docs/stm32f411re-board.md), [GPIOA/RCC subset](docs/stm32f411re-gpioa.md), [ELF parser subset](docs/elf32-arm-subset.md), and [test firmware execution](docs/test-firmware-execution.md). PC and exception behavior are not a complete Cortex-M implementation.

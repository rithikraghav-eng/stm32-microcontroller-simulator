# STM32F411RE GPIOA and RCC subset

## Hardware sources

Register locations and reset semantics are based on ST's [RM0383 reference
manual (DM00119316)](https://www.st.com/resource/en/reference_manual/dm00119316.pdf),
notably the RCC register description for `RCC_AHB1ENR` and GPIO register
descriptions for `GPIOx_MODER`, `GPIOx_IDR`, `GPIOx_ODR`, and `GPIOx_BSRR`.
The target device is the STM32F411RE.

| Register | Address | Implemented reset value |
|---|---:|---:|
| `RCC_AHB1ENR` | `0x40023830` | GPIOAEN bit 0 is clear |
| `GPIOA_MODER` | `0x40020000` | `0xA8000000` |
| `GPIOA_IDR` | `0x40020010` | external simulated inputs default low |
| `GPIOA_ODR` | `0x40020014` | `0x00000000` |
| `GPIOA_BSRR` | `0x40020018` | write-only; no stored reset value |

`RCC_AHB1ENR.GPIOAEN` is bit 0. GPIOA's clock is disabled at reset. GPIOA
register access while the clock is disabled is rejected by this emulator with
`PermissionError`, representing the reference manual's requirement that the
port clock be enabled before use; the emulator does not model a Cortex-M bus
fault exception.

## Supported emulator behavior

Only the registers in the table are modeled. The AHB1ENR model supports only
GPIOAEN; attempts to write 1 to any other bit raise `NotImplementedError`, and
unmodeled RCC bits read as zero. Other GPIOA offsets also raise
`NotImplementedError`.

This peripheral interface accepts aligned 32-bit accesses only. This is an
emulator subset contract; it is not a statement that the silicon bus rejects
all byte or halfword transfers. No alignment fault behavior is modeled.

`MODER` stores the two-bit mode for each pin. The reset value matches the
documented GPIO mode reset state, including alternate-function modes on pins
13–15; alternate-function and analog electrical behavior is not simulated.
`ODR` and `BSRR` update the output latch. BSRR low-half bits set corresponding
ODR bits and high-half bits reset them; for the same pin set takes precedence.
`IDR` reports the ODR latch for pins in output mode and the separately supplied
external input level for all other modes.

Use `board.gpioa.set_input_level(pin, level)` to supply an external digital
input. `board.gpioa.get_output_level(pin)` returns the effective ODR level for
a pin configured as output, otherwise `None`. Reset restores GPIO register
defaults and clears simulated external input levels. This model does not
simulate electrical contention, pull resistors, alternate functions, analog
modes, speed/type registers, EXTI, or pin-level timing.

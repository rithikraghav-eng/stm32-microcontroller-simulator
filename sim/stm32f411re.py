from __future__ import annotations

from dataclasses import dataclass

from .bus import MemoryMap
from .cpu import CPU
from .elf import ELF32Image, ELF32Segment, PF_X
from .gpio import GPIOA, GPIO_REGISTER_BLOCK_SIZE, GPIOA_BASE, RCC, RCC_BASE
from .memory import Memory

FLASH_BASE = 0x08000000
FLASH_SIZE = 512 * 1024
SRAM_BASE = 0x20000000
SRAM_SIZE = 128 * 1024


class FirmwareLoadError(ValueError):
    """Firmware image is invalid for this board's mapped load regions."""


class FirmwareExecutionError(RuntimeError):
    """A test firmware run failed or exhausted its execution budget."""


@dataclass(frozen=True)
class LoadedSegment:
    address: int
    file_size: int
    memory_size: int
    runtime_address: int | None = None


@dataclass(frozen=True)
class FirmwareLoadResult:
    entry_point: int
    segments: tuple[LoadedSegment, ...]


@dataclass(frozen=True)
class FirmwareExecutionResult:
    entry_point: int
    initial_stack_pointer: int
    instructions_executed: int
    registers: tuple[int, ...]
    flags: tuple[int, int, int, int]
    termination: str


class STM32F411REBoard:
    """Minimal Flash/SRAM and GPIOA/RCC board map for the STM32F411RE."""

    def __init__(self) -> None:
        self.flash = Memory(size=FLASH_SIZE)
        self.sram = Memory(size=SRAM_SIZE)
        self.rcc = RCC()
        self.gpioa = GPIOA(self.rcc)
        self.bus = MemoryMap()
        self.bus.map_region(
            FLASH_BASE,
            FLASH_SIZE,
            self.flash,
            readable=True,
            writable=False,
            loader_writable=True,
        )
        self.bus.map_region(
            SRAM_BASE,
            SRAM_SIZE,
            self.sram,
            readable=True,
            writable=True,
        )
        self.bus.map_region(
            GPIOA_BASE,
            GPIO_REGISTER_BLOCK_SIZE,
            self.gpioa,
            loader_writable=False,
        )
        self.bus.map_region(
            RCC_BASE,
            GPIO_REGISTER_BLOCK_SIZE,
            self.rcc,
            loader_writable=False,
        )
        self.cpu = CPU(memory=self.bus)

    def load_firmware(self, image: ELF32Image) -> FirmwareLoadResult:
        """Load a parsed ELF image without changing CPU/reset state.

        The explicit loader permission permits initialization of Flash while
        ordinary CPU stores to the same mapping remain denied.
        """
        if not isinstance(image, ELF32Image):
            raise TypeError("image must be a parsed ELF32Image")
        if not image.segments:
            raise FirmwareLoadError("Firmware image contains no loadable segments")

        validated_segments: list[tuple[ELF32Segment, int, bytes]] = []
        planned_writes: list[tuple[int, int, bytes, str]] = []
        for index, segment in enumerate(image.segments):
            if not isinstance(segment, ELF32Segment):
                raise FirmwareLoadError(f"Segment {index} has an invalid representation")
            if (
                segment.file_size < 0
                or segment.memory_size < segment.file_size
                or segment.file_size != len(segment.data)
            ):
                raise FirmwareLoadError(
                    f"Segment {index} has inconsistent file/memory sizes"
                )
            load_address = segment.load_address
            runtime_address = segment.virtual_address
            if (
                load_address < 0
                or load_address + segment.file_size > 0x1_0000_0000
            ):
                raise FirmwareLoadError(
                    f"Segment {index} file load range overflows the 32-bit "
                    "address space"
                )
            if (
                runtime_address < 0
                or runtime_address + segment.memory_size > 0x1_0000_0000
            ):
                raise FirmwareLoadError(
                    f"Segment {index} runtime range overflows the 32-bit "
                    "address space"
                )
            initialized_data = segment.data
            runtime_payload = initialized_data + bytes(
                segment.memory_size - segment.file_size
            )
            try:
                if load_address == runtime_address:
                    self.bus.validate_load_access(
                        runtime_address, segment.memory_size
                    )
                    if runtime_payload:
                        planned_writes.append(
                            (index, runtime_address, runtime_payload, "runtime")
                        )
                else:
                    self.bus.validate_load_access(
                        load_address, segment.file_size
                    )
                    self.bus.validate_load_access(
                        runtime_address, segment.memory_size
                    )
                    if initialized_data:
                        planned_writes.append(
                            (index, load_address, initialized_data, "load")
                        )
                    if runtime_payload:
                        planned_writes.append(
                            (index, runtime_address, runtime_payload, "runtime")
                        )
            except (IndexError, PermissionError, ValueError) as error:
                raise FirmwareLoadError(
                    f"Segment {index} load/runtime range is not loadable: {error}"
                ) from error
            validated_segments.append((segment, load_address, runtime_payload))

        for write_index, (segment_index, address, payload, kind) in enumerate(
            planned_writes
        ):
            write_end = address + len(payload)
            for other_index, other_address, other_payload, other_kind in planned_writes[
                :write_index
            ]:
                other_end = other_address + len(other_payload)
                if address < other_end and other_address < write_end:
                    raise FirmwareLoadError(
                        f"Segment {segment_index} {kind} range "
                        f"0x{address:08X}..0x{write_end - 1:08X} overlaps "
                        f"segment {other_index} {other_kind} range "
                        f"0x{other_address:08X}..0x{other_end - 1:08X}"
                    )

        for _segment_index, address, payload, _kind in planned_writes:
            self.bus.load_write(address, payload)

        return FirmwareLoadResult(
            entry_point=image.entry_point,
            segments=tuple(
                LoadedSegment(
                    address=address,
                    file_size=segment.file_size,
                    memory_size=segment.memory_size,
                    runtime_address=segment.virtual_address,
                )
                for segment, address, _payload in validated_segments
            ),
        )

    def run_test_firmware(
        self, image: ELF32Image, *, max_instructions: int = 1000
    ) -> FirmwareExecutionResult:
        """Run a loaded image in the explicit BKPT-terminated test mode.

        The image's odd ELF entry denotes Thumb state; the internal PC is
        aligned by clearing bit 0. SP is initialized to the top of SRAM. CPU
        registers and flags are reset, while Flash, SRAM, and peripheral state
        are otherwise left as initialized by the image loader/current board.
        The exact ``BKPT #0`` halfword (0xBE00) stops the harness without
        executing that instruction. This does not model the MCU reset path.
        """
        if max_instructions < 0:
            raise ValueError("max_instructions must be non-negative")
        if not isinstance(image, ELF32Image):
            raise TypeError("image must be a parsed ELF32Image")
        if image.entry_point & 1 == 0:
            raise FirmwareExecutionError(
                f"Test execution requires a Thumb ELF entry point, got "
                f"0x{image.entry_point:08X}"
            )
        entry = image.entry_point & ~1
        if not any(
            segment.flags & PF_X
            and segment.load_address <= entry
            and entry < segment.load_address + segment.memory_size
            for segment in image.segments
        ):
            raise FirmwareExecutionError(
                f"ELF entry point 0x{image.entry_point:08X} is not in an "
                "executable loaded segment"
            )

        self.load_firmware(image)
        initial_sp = SRAM_BASE + SRAM_SIZE
        self.cpu.reset(pc=entry, sp=initial_sp)

        while True:
            address = self.cpu.pc
            try:
                instruction = self.bus.read16(address)
            except (IndexError, PermissionError) as error:
                if self.cpu.instructions_executed >= max_instructions:
                    raise FirmwareExecutionError(
                        f"Instruction budget exhausted after {max_instructions} "
                        f"instructions at PC 0x{address:08X}"
                    ) from error
                raise FirmwareExecutionError(
                    f"Memory access failed at PC 0x{address:08X}: {error}"
                ) from error

            if instruction == 0xBE00:
                return FirmwareExecutionResult(
                    entry_point=image.entry_point,
                    initial_stack_pointer=initial_sp,
                    instructions_executed=self.cpu.instructions_executed,
                    registers=tuple(self.cpu.regs),
                    flags=(self.cpu.N, self.cpu.Z, self.cpu.C, self.cpu.V),
                    termination="BKPT #0",
                )

            if self.cpu.instructions_executed >= max_instructions:
                raise FirmwareExecutionError(
                    f"Instruction budget exhausted after {max_instructions} "
                    f"instructions at PC 0x{address:08X}"
                )

            try:
                self.cpu.step()
            except NotImplementedError as error:
                raise FirmwareExecutionError(
                    f"Unsupported instruction at 0x{address:08X} "
                    f"(0x{instruction:04X}): {error}"
                ) from error
            except (IndexError, PermissionError) as error:
                raise FirmwareExecutionError(
                    f"Memory access failed at 0x{address:08X} "
                    f"(instruction 0x{instruction:04X}): {error}"
                ) from error

    def reset(self) -> None:
        """Clear modeled SRAM and reset CPU state from the Flash vectors.

        Flash is retained. Populate the vector words through ``flash`` before
        reset; CPU stores through ``bus`` remain blocked by the Flash mapping.
        """
        initial_sp = self.bus.read32(FLASH_BASE)
        reset_vector = self.bus.read32(FLASH_BASE + 4)
        if reset_vector & 1 == 0:
            raise ValueError(
                f"Reset vector 0x{reset_vector:08X} is not a Thumb address"
            )

        self.sram.clear()
        self.rcc.reset()
        self.gpioa.reset()
        self.cpu.reset(pc=reset_vector & ~1, sp=initial_sp)

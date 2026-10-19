from __future__ import annotations

from dataclasses import dataclass
import struct

ELF32_HEADER = struct.Struct("<16sHHIIIIIHHHHHH")
ELF32_PROGRAM_HEADER = struct.Struct("<IIIIIIII")
ELF_MAGIC = b"\x7fELF"
ELFCLASS32 = 1
ELFDATA2LSB = 1
EV_CURRENT = 1
ET_EXEC = 2
EM_ARM = 40
PT_LOAD = 1
PT_DYNAMIC = 2
PT_INTERP = 3
PF_X = 1
MAX_ADDRESS = 1 << 32


class ELFError(ValueError):
    """Invalid or unsupported ELF input for this emulator subset."""


@dataclass(frozen=True)
class ELF32Segment:
    offset: int
    virtual_address: int
    physical_address: int
    file_size: int
    memory_size: int
    flags: int
    alignment: int
    data: bytes

    @property
    def load_address(self) -> int:
        """Return the physical load address, falling back to virtual address."""
        return self.physical_address or self.virtual_address


@dataclass(frozen=True)
class ELF32Image:
    entry_point: int
    flags: int
    segments: tuple[ELF32Segment, ...]


def parse_elf32_arm(data: bytes | bytearray | memoryview) -> ELF32Image:
    """Parse a strict, dependency-free subset of ELF32 little-endian ARM ET_EXEC."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("ELF input must be bytes-like")
    blob = memoryview(data)
    if len(blob) < ELF32_HEADER.size:
        raise ELFError("Truncated ELF32 header")

    (
        ident,
        elf_type,
        machine,
        version,
        entry_point,
        program_header_offset,
        _section_header_offset,
        flags,
        header_size,
        program_header_entry_size,
        program_header_count,
        _section_header_entry_size,
        _section_header_count,
        _section_name_index,
    ) = ELF32_HEADER.unpack_from(blob)

    if ident[:4] != ELF_MAGIC:
        raise ELFError("Invalid ELF magic")
    if ident[4] != ELFCLASS32:
        raise ELFError("Only ELF32 files are supported")
    if ident[5] != ELFDATA2LSB:
        raise ELFError("Only little-endian ELF files are supported")
    if ident[6] != EV_CURRENT or version != EV_CURRENT:
        raise ELFError("Unsupported ELF version")
    if elf_type != ET_EXEC:
        raise ELFError("Only statically linked ELF executable files are supported")
    if machine != EM_ARM:
        raise ELFError(f"Unsupported ELF architecture (e_machine={machine})")
    if header_size != ELF32_HEADER.size:
        raise ELFError(f"Invalid ELF32 header size {header_size}")
    if program_header_entry_size != ELF32_PROGRAM_HEADER.size:
        raise ELFError(
            f"Invalid ELF32 program header size {program_header_entry_size}"
        )
    if program_header_count == 0 or program_header_count == 0xFFFF:
        raise ELFError("ELF must have a supported, non-empty program header table")

    table_size = program_header_entry_size * program_header_count
    table_end = program_header_offset + table_size
    if (
        program_header_offset < header_size
        or table_end > len(blob)
        or table_end > MAX_ADDRESS
    ):
        raise ELFError("Program header table is outside the ELF file")

    segments: list[ELF32Segment] = []
    for index in range(program_header_count):
        offset = program_header_offset + index * program_header_entry_size
        (
            segment_type,
            file_offset,
            virtual_address,
            physical_address,
            file_size,
            memory_size,
            segment_flags,
            alignment,
        ) = ELF32_PROGRAM_HEADER.unpack_from(blob, offset)

        if segment_type in (PT_DYNAMIC, PT_INTERP):
            raise ELFError("Dynamic linking and interpreters are unsupported")
        if segment_type != PT_LOAD:
            continue
        if file_size > memory_size:
            raise ELFError(f"PT_LOAD segment {index} has p_filesz greater than p_memsz")
        if file_offset + file_size > len(blob):
            raise ELFError(f"PT_LOAD segment {index} data is outside the ELF file")
        if virtual_address + memory_size > MAX_ADDRESS:
            raise ELFError(f"PT_LOAD segment {index} virtual range overflows ELF32")
        if physical_address + memory_size > MAX_ADDRESS:
            raise ELFError(f"PT_LOAD segment {index} physical range overflows ELF32")
        if alignment not in (0, 1):
            if alignment & (alignment - 1):
                raise ELFError(f"PT_LOAD segment {index} alignment is not a power of two")
            if (virtual_address - file_offset) & (alignment - 1):
                raise ELFError(
                    f"PT_LOAD segment {index} virtual address and file offset "
                    "are incongruent"
                )

        segments.append(
            ELF32Segment(
                offset=file_offset,
                virtual_address=virtual_address,
                physical_address=physical_address,
                file_size=file_size,
                memory_size=memory_size,
                flags=segment_flags,
                alignment=alignment,
                data=bytes(blob[file_offset:file_offset + file_size]),
            )
        )

    if not segments:
        raise ELFError("ELF contains no loadable PT_LOAD segments")

    entry_address = entry_point & ~1
    if not any(
        segment.flags & PF_X
        and segment.virtual_address <= entry_address
        and entry_address < segment.virtual_address + segment.memory_size
        for segment in segments
    ):
        raise ELFError("ELF entry point is outside executable PT_LOAD segments")

    return ELF32Image(
        entry_point=entry_point,
        flags=flags,
        segments=tuple(segments),
    )

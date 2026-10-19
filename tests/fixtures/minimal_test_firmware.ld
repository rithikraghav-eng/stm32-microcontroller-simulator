ENTRY(firmware_entry)

SECTIONS
{
    . = 0x08001000;
    .text : ALIGN(4)
    {
        KEEP(*(.text.firmware_entry))
        *(.text*)
    }

    /DISCARD/ :
    {
        *(.ARM.exidx*)
        *(.ARM.extab*)
        *(.comment*)
        *(.note*)
    }
}

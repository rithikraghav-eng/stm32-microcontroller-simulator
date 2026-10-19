ENTRY(main)

MEMORY
{
    FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
    SRAM (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}

PHDRS
{
    flash PT_LOAD FLAGS(5);
    ram PT_LOAD FLAGS(6);
}

SECTIONS
{
    .text : ALIGN(4)
    {
        *(.text*)
        *(.rodata*)
    } > FLASH :flash

    .data : ALIGN(4)
    {
        *(.data*)
    } > SRAM AT> FLASH :ram

    .bss (NOLOAD) : ALIGN(4)
    {
        *(.bss*)
        *(COMMON)
    } > SRAM :ram

    /DISCARD/ :
    {
        *(.ARM.exidx*)
        *(.ARM.extab*)
        *(.comment*)
        *(.note*)
    }
}

.syntax unified
.cpu cortex-m4
.thumb

.section .text.firmware_entry, "ax", %progbits
.global firmware_entry
.type firmware_entry, %function
.thumb_func
firmware_entry:
    movs r0, #20
    adds r0, #22
    bkpt #0
.size firmware_entry, .-firmware_entry

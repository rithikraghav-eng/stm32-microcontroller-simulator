.syntax unified
.thumb
.text
.global _start
_start:
    mov r0, r1
    add r2, r0, r1
    sub r3, r4, r5
    and r6, r7
    eor r0, r1
    orr r0, r1
    bic r0, r1
    mvn r0, r1
    lsl r0, r1
    lsr r0, r1
    asr r0, r1
    bx lr
